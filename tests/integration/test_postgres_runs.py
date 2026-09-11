"""Real PostgreSQL and LangGraph evidence uses an explicit isolated test connection."""

import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection, sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import DictRow
from psycopg_pool import ConnectionPool

from factorforge.auth.principal import Principal
from factorforge.domain.errors import ResearchError
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.postgres_runs import PostgresRunStore


@pytest.fixture
def identity() -> Principal:
    """Test identities are explicit principals, not claims about Cognito verification."""
    return Principal("fixture-issuer", "alice", frozenset({"create_run", "read_own_run"}))


@pytest.fixture
def database() -> tuple[str, str]:
    """Never fall back to a development or production DSN when integration settings are absent."""
    dsn = os.environ.get("FACTORFORGE_TEST_DSN")
    if not dsn:
        pytest.skip("Set FACTORFORGE_TEST_DSN to an isolated PostgreSQL test database")
    return dsn, "ff_test_" + uuid4().hex


@pytest.fixture
def store(database: tuple[str, str]) -> Iterator[PostgresRunStore]:
    """Each test owns fresh schemas; preserve evidence instead of broad cleanup operations."""
    instance = PostgresRunStore(database[0], schema=database[1], require_test_database=True)
    yield instance
    instance.close()


def test_owner_scoped_atomic_replay(store: PostgresRunStore, identity: Principal) -> None:
    """Identical keys collide only for one owner and decimal formatting preserves equality."""
    brief = ResearchBrief(idea="Investigate momentum", max_llm_cost_usd=Decimal("5"))

    def create(_: int) -> UUID:
        """Competing connections must rely on the SQL constraint rather than a process lock."""
        return store.create(brief, "same", identity).run_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        identifiers = list(pool.map(create, range(8)))
    assert len(set(identifiers)) == 1
    alternate = ResearchBrief(idea=brief.idea, max_llm_cost_usd=Decimal("5.00"))
    assert store.create(alternate, "same", identity).run_id == identifiers[0]
    with pytest.raises(ResearchError) as conflict:
        store.create(ResearchBrief(idea="Investigate value"), "same", identity)
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    other = Principal(identity.issuer, "bob", identity.capabilities)
    assert store.create(brief, "same", other).run_id != identifiers[0]
    with pytest.raises(ResearchError) as hidden:
        store.get(identifiers[0], other)
    assert hidden.value.code == "RUN_NOT_FOUND"


def test_checkpoint_survives_store_restart(database: tuple[str, str], identity: Principal) -> None:
    """A new saver instance reads the persisted graph rather than inheriting Python memory."""
    first = PostgresRunStore(database[0], schema=database[1], require_test_database=True)
    run = first.create(ResearchBrief(idea="Investigate   momentum"), "restart", identity)
    normalized = first.normalize(run.run_id, identity)
    assert normalized.storage == "postgres"
    assert normalized.brief == "Investigate momentum"
    checkpoint = first.checkpoint_id(run.run_id, identity)
    assert checkpoint
    first.close()
    second = PostgresRunStore(database[0], schema=database[1], require_test_database=True)
    try:
        assert second.ready()
        assert second.get(run.run_id, identity) == normalized
        assert second.normalize(run.run_id, identity) == normalized
        assert second.checkpoint_id(run.run_id, identity) == checkpoint
        assert len(second.get(run.run_id, identity).events) == 2
    finally:
        second.close()


def test_checkpoint_ahead_recovery(database: tuple[str, str], identity: Principal) -> None:
    """A checkpoint commit followed by failed canonical publication is recoverable without rerun."""

    def crash(stage: str) -> None:
        """Inject exactly the cross-transaction failure that a database mock would conceal."""
        if stage == "after_checkpoint":
            raise RuntimeError("simulated publication failure")

    first = PostgresRunStore(
        database[0], schema=database[1], require_test_database=True, failpoint=crash
    )
    run = first.create(ResearchBrief(idea="Investigate momentum"), "crash", identity)
    with pytest.raises(RuntimeError, match="publication"):
        first.normalize(run.run_id, identity)
    assert first.get(run.run_id, identity).status == "RECEIVED"
    checkpoint = first.checkpoint_id(run.run_id, identity)
    assert checkpoint
    first.close()
    second = PostgresRunStore(database[0], schema=database[1], require_test_database=True)
    try:
        assert second.recover_pending() == 1
        assert second.get(run.run_id, identity).status == "BRIEF_NORMALIZED"
        assert second.checkpoint_id(run.run_id, identity) == checkpoint
        assert second.recover_pending() == 0
    finally:
        second.close()


def test_lost_background_schedule_survives_process_exit(
    database: tuple[str, str], store: PostgresRunStore, identity: Principal
) -> None:
    """A receipt committed in an abruptly exited process remains discoverable work."""
    program = """
import os
from factorforge.auth.principal import Principal
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.postgres_runs import PostgresRunStore
store = PostgresRunStore(
    os.environ['FACTORFORGE_TEST_DSN'], schema=os.environ['FF_TEST_SCHEMA'],
    require_test_database=True,
)
run = store.create(
    ResearchBrief(idea='Investigate momentum'), 'lost-schedule',
    Principal('fixture-issuer','alice',frozenset()),
)
print(run.run_id, flush=True)
os._exit(0)
"""
    environment = dict(os.environ, FACTORFORGE_TEST_DSN=database[0], FF_TEST_SCHEMA=database[1])
    result = subprocess.run(
        [sys.executable, "-c", program], env=environment, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, "Isolated writer process failed"
    run_id = UUID(result.stdout.strip())
    assert store.get(run_id, identity).status == "RECEIVED"
    assert store.recover_pending() == 1
    assert store.get(run_id, identity).status == "BRIEF_NORMALIZED"


@pytest.mark.parametrize("stage", ["before_checkpoint", "before_publication_commit"])
def test_failure_windows_preserve_canonical_state(
    database: tuple[str, str], identity: Principal, stage: str
) -> None:
    """Neither partial graph execution nor a rolled-back event can advance accepted state."""

    def crash(actual: str) -> None:
        """Fail once at the specified transaction boundary without simulating database storage."""
        if actual == stage:
            raise RuntimeError("injected failure")

    instance = PostgresRunStore(
        database[0], schema=database[1], require_test_database=True, failpoint=crash
    )
    try:
        run = instance.create(ResearchBrief(idea="Investigate value"), "failure", identity)
        with pytest.raises(RuntimeError, match="injected"):
            instance.normalize(run.run_id, identity)
        record = instance.get(run.run_id, identity)
        assert record.status == "RECEIVED"
        assert len(record.events) == 1
        instance.failpoint = None
        assert instance.recover_pending() == 1
        assert len(instance.get(run.run_id, identity).events) == 2
    finally:
        instance.close()


def test_creation_rollback_and_postcommit_retry(
    store: PostgresRunStore, identity: Principal
) -> None:
    """A rollback frees the receipt key while a lost acknowledgement preserves committed results."""

    def crash(stage: str) -> None:
        """The two fault positions distinguish rollback from an already committed result."""
        if stage in {"before_create_commit", "after_publication_commit"}:
            raise RuntimeError("injected transaction boundary")

    store.failpoint = crash
    with pytest.raises(RuntimeError):
        store.create(ResearchBrief(idea="Discard this rolled back idea"), "retry", identity)
    store.failpoint = None
    run = store.create(ResearchBrief(idea="A different valid idea"), "retry", identity)
    store.failpoint = crash
    with pytest.raises(RuntimeError):
        store.normalize(run.run_id, identity)
    store.failpoint = None
    assert store.normalize(run.run_id, identity).status == "BRIEF_NORMALIZED"
    assert len(store.get(run.run_id, identity).events) == 2


def test_pending_graph_resumes_and_missing_checkpoint_fails_closed(
    store: PostgresRunStore, identity: Principal
) -> None:
    """Exercise a genuinely paused graph and reject canonical evidence whose checkpoint was lost."""
    run = store.create(ResearchBrief(idea="Investigate momentum"), "pause", identity)
    with store._connection() as connection:
        expected = store._expected(store._owned(connection, run.run_id, identity))
    config = store._graph.config(str(run.run_id))
    store._graph.graph.invoke(
        expected, config, durability="sync", interrupt_before=["normalize_brief"]
    )
    assert store._graph.graph.get_state(config).next == ("normalize_brief",)
    assert store.normalize(run.run_id, identity).status == "BRIEF_NORMALIZED"
    store._graph.saver.delete_thread(str(run.run_id))
    with pytest.raises(ResearchError) as missing:
        store.normalize(run.run_id, identity)
    assert missing.value.code == "CHECKPOINT_MISSING"
    with pytest.raises(ResearchError) as missing_read:
        store.get(run.run_id, identity)
    assert missing_read.value.code == "CHECKPOINT_MISSING"


def test_checkpoint_owner_corruption_and_version_mismatch(
    store: PostgresRunStore, identity: Principal
) -> None:
    """Checkpoint contents cannot authorize publication for another owner or graph version."""
    run = store.create(ResearchBrief(idea="Investigate momentum"), "corrupt", identity)
    with store._connection() as connection:
        expected = store._expected(store._owned(connection, run.run_id, identity))
    expected["owner_subject"] = "other-user"
    store._graph.graph.invoke(expected, store._graph.config(str(run.run_id)), durability="sync")
    with pytest.raises(ResearchError) as mismatch:
        store.normalize(run.run_id, identity)
    assert mismatch.value.code == "CHECKPOINT_CONFLICT"
    assert store.get(run.run_id, identity).status == "RECEIVED"
    store.graph_version = "unrecognized-v2"
    with pytest.raises(ResearchError) as version:
        store.normalize(run.run_id, identity)
    assert version.value.code == "CHECKPOINT_CONFLICT"


def test_closed_store_is_unavailable(store: PostgresRunStore, identity: Principal) -> None:
    """Dependency closure cannot silently replace durable state with a new memory store."""
    store.close()
    store.close()
    assert not store.ready()
    with pytest.raises(ResearchError) as unavailable:
        store.create(ResearchBrief(idea="Investigate momentum"), "closed", identity)
    assert unavailable.value.code == "DEPENDENCY_UNAVAILABLE"


def test_real_connection_failure_and_isolation_guards(database: tuple[str, str]) -> None:
    """Reject unsafe targets before migrations and sanitize a real failed TCP connection."""
    with pytest.raises(ValueError, match="schema"):
        PostgresRunStore(database[0], schema="public")
    with pytest.raises(ValueError, match="unrelated"):
        PostgresRunStore(make_conninfo(database[0], dbname="postgres"), require_test_database=True)
    with pytest.raises(ResearchError) as unavailable:
        PostgresRunStore(make_conninfo(database[0], host="127.0.0.1", port=1))
    assert unavailable.value.code == "DEPENDENCY_UNAVAILABLE"
    assert "postgresql://" not in str(unavailable.value)


def test_lost_checkpoint_connection_fails_readiness(
    store: PostgresRunStore, identity: Principal
) -> None:
    """Healthy canonical storage cannot hide an unavailable checkpoint dependency."""
    run = store.create(ResearchBrief(idea="Investigate value"), "checkpoint-down", identity)
    store._checkpoint_connection.close()
    assert not store.ready()
    with pytest.raises(ResearchError) as unavailable:
        store.normalize(run.run_id, identity)
    assert unavailable.value.code == "DEPENDENCY_UNAVAILABLE"
    assert store.get(run.run_id, identity).status == "RECEIVED"
    with pytest.raises(ValueError, match="batch"):
        store.recover_pending(limit=0)


@pytest.mark.parametrize("corruption", [{"status": "COMPLETED"}, {"brief": "invented result"}])
def test_checkpoint_output_is_verified(
    store: PostgresRunStore, identity: Principal, corruption: dict[str, str]
) -> None:
    """A matching owner does not make corrupted checkpoint output valid research state."""
    run = store.create(ResearchBrief(idea="Investigate momentum"), "output-check", identity)
    with store._connection() as connection:
        expected = store._expected(store._owned(connection, run.run_id, identity))
    config = store._graph.config(str(run.run_id))
    store._graph.graph.invoke(expected, config, durability="sync")
    store._graph.graph.update_state(config, corruption)
    with pytest.raises(ResearchError) as invalid:
        store.normalize(run.run_id, identity)
    assert invalid.value.code == "CHECKPOINT_CONFLICT"
    assert store.get(run.run_id, identity).status == "RECEIVED"


def test_poison_recovery_rotates_without_starving_new_work(
    store: PostgresRunStore, identity: Principal
) -> None:
    """A persistent version conflict is visible but cannot monopolize a bounded scan batch."""
    poison = store.create(ResearchBrief(idea="Older poisoned run"), "poison", identity)
    with store._connection() as connection:
        connection.execute(
            "UPDATE research_runs SET graph_version='incompatible' WHERE run_id=%s",
            (poison.run_id,),
        )
    healthy = store.create(ResearchBrief(idea="Healthy later run"), "healthy", identity)
    assert store.recover_pending(limit=1) == 0
    assert store.recover_pending(limit=1) == 1
    assert store.get(healthy.run_id, identity).status == "BRIEF_NORMALIZED"
    with store._connection() as connection:
        row = connection.execute(
            "SELECT recovery_attempts,recovery_error_code FROM research_runs WHERE run_id=%s",
            (poison.run_id,),
        ).fetchone()
    assert row == {"recovery_attempts": 1, "recovery_error_code": "CHECKPOINT_CONFLICT"}


def test_pool_driver_diagnostics_are_redacted(
    store: PostgresRunStore, caplog: pytest.LogCaptureFixture
) -> None:
    """Library background reconnect logs cannot bypass the API's safe error envelopes."""
    logging.getLogger("psycopg.pool").warning(
        "error connecting in '%s': password=TEST_SENTINEL", store._pool.name
    )
    assert "TEST_SENTINEL" not in caplog.text
    assert "driver details redacted" in caplog.text


def test_malformed_checkpoint_blob_isolated_from_recovery_batch(
    database: tuple[str, str], store: PostgresRunStore, identity: Principal
) -> None:
    """Actual malformed database bytes must not tear down the asynchronous recovery supervisor."""
    poison = store.create(ResearchBrief(idea="Poisoned serialized idea"), "bad-bytes", identity)
    with store._connection() as connection:
        expected = store._expected(store._owned(connection, poison.run_id, identity))
    store._graph.graph.invoke(expected, store._graph.config(str(poison.run_id)), durability="sync")
    # Strings are inlined; an invalid list creates a real blob to corrupt in this test.
    store._graph.graph.update_state(store._graph.config(str(poison.run_id)), {"idea": ["invalid"]})
    changed = store._checkpoint_connection.execute(
        sql.SQL(
            "UPDATE {}.checkpoint_blobs SET blob=%s WHERE thread_id=%s AND channel='idea'"
        ).format(sql.Identifier(database[1] + "_checkpoints")),
        (b"\xc1", str(poison.run_id)),
    )
    assert changed.rowcount > 0
    healthy = store.create(ResearchBrief(idea="A later healthy idea"), "after-bytes", identity)
    assert store.recover_pending() == 1
    assert store.get(healthy.run_id, identity).status == "BRIEF_NORMALIZED"
    with store._connection() as connection:
        row = connection.execute(
            "SELECT recovery_error_code FROM research_runs WHERE run_id=%s", (poison.run_id,)
        ).fetchone()
    assert row == {"recovery_error_code": "CHECKPOINT_CORRUPT"}


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("unsafe setup detail"),
        ResearchError("DEPENDENCY_UNAVAILABLE", "Safe setup failure.", 503),
    ],
)
def test_partial_initialization_releases_resources(
    database: tuple[str, str], monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    """Failed startup must release pools, checkpoint connections and logging filters."""
    original_close = ConnectionPool.close
    closed_pools: list[str] = []
    checkpoint_connections: list[Connection[DictRow]] = []
    filters_before = list(logging.getLogger("psycopg.pool").filters)

    def capture_close(pool: ConnectionPool[Connection[DictRow]], timeout: float = 5) -> None:
        """Observe cleanup of the real connection pool without replacing its behavior."""
        closed_pools.append(pool.name)
        original_close(pool, timeout)

    def fail_setup(saver: PostgresSaver) -> None:
        """Fail only after canonical pool and checkpoint connection have been allocated."""
        assert isinstance(saver.conn, Connection)
        checkpoint_connections.append(saver.conn)
        raise failure

    monkeypatch.setattr(ConnectionPool, "close", capture_close)
    monkeypatch.setattr(PostgresSaver, "setup", fail_setup)
    with pytest.raises(ResearchError) as unavailable:
        PostgresRunStore(database[0], schema=database[1], require_test_database=True)
    assert unavailable.value.code == "DEPENDENCY_UNAVAILABLE"
    assert "unsafe setup detail" not in str(unavailable.value)
    assert closed_pools
    assert all(connection.closed for connection in checkpoint_connections)
    assert logging.getLogger("psycopg.pool").filters == filters_before
