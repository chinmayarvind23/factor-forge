"""Canonical PostgreSQL records publish only after an actual LangGraph checkpoint persists."""

import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection, sql
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from factorforge.auth.principal import Principal
from factorforge.domain.errors import ResearchError
from factorforge.domain.research_brief import ResearchBrief, RunRecord
from factorforge.orchestration.normalization_graph import NormalizationGraph, NormalizationState


class PoolLogRedaction(logging.Filter):
    """Driver reconnect errors are not trusted to exclude connection credentials."""

    def __init__(self, pool_name: str) -> None:
        """Scope redaction to this store's pool rather than suppressing unrelated diagnostics."""
        super().__init__()
        self.pool_name = pool_name

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep a safe failure signal while removing driver messages and exception details."""
        if record.levelno >= logging.WARNING and self.pool_name in record.getMessage():
            record.msg = "FactorForge PostgreSQL pool is unavailable; driver details redacted."
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


class StorageConfigurationError(ValueError):
    """A safe target guard error is distinct from opaque dependency initialization failures."""


def canonical_request(brief: ResearchBrief) -> dict[str, object]:
    """Fixed decimal formatting preserves equal requests across transport representations."""
    return {
        "idea": brief.idea,
        "max_llm_cost_usd": format(brief.max_llm_cost_usd, ".2f"),
        "max_wall_time_s": brief.max_wall_time_s,
        "max_experiments": brief.max_experiments,
    }


def request_hash(brief: ResearchBrief) -> str:
    """A versioned canonical payload gives checkpoints a stable immutable input fingerprint."""
    encoded = json.dumps(canonical_request(brief), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(("request-v1:" + encoded).encode()).hexdigest()


class PostgresRunStore:
    """Synchronous operations must run off the API event loop in a bounded worker pool."""

    def __init__(
        self,
        dsn: str,
        *,
        schema: str = "factorforge",
        graph_version: str = "normalize-v1",
        failpoint: Callable[[str], None] | None = None,
        require_test_database: bool = False,
    ) -> None:
        """Provision only dedicated FactorForge databases and explicitly isolated schemas."""
        if not re.fullmatch(r"(?:factorforge|ff_test_[a-f0-9]{32})", schema):
            raise ValueError("Use a FactorForge application or generated test schema")
        self.graph_version = graph_version
        self.failpoint = failpoint
        self._closed = False
        self._initialize(dsn, schema, require_test_database)

    def _initialize(self, dsn: str, schema: str, require_test_database: bool) -> None:
        """Package migrations and application migrations use separate schema search paths."""
        try:
            with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as connection:
                database = connection.execute("SELECT current_database()").fetchone()
                name = str(database[0]) if database else ""
                allowed = (
                    name.startswith("factorforge_test_")
                    if require_test_database
                    else (name == "factorforge" or name.startswith("factorforge_"))
                )
                if not allowed:
                    raise StorageConfigurationError(
                        "Refusing to initialize an unrelated PostgreSQL database"
                    )
                for target in (schema, schema + "_checkpoints"):
                    connection.execute(
                        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(target))
                    )
            pool_name = "factorforge-" + uuid4().hex
            self._log_filter = PoolLogRedaction(pool_name)
            logging.getLogger("psycopg.pool").addFilter(self._log_filter)
            self._pool: ConnectionPool[Connection[DictRow]] = ConnectionPool(
                dsn,
                name=pool_name,
                min_size=1,
                max_size=4,
                open=False,
                timeout=5,
                max_waiting=16,
                kwargs={
                    "autocommit": True,
                    "row_factory": dict_row,
                    "connect_timeout": 5,
                    "options": (
                        f"-csearch_path={schema} -cstatement_timeout=10000 -clock_timeout=5000"
                    ),
                },
            )
            self._pool.open(wait=True, timeout=5)
            with self._connection() as connection:
                for name in (
                    "001_research_runs.sql",
                    "002_research_budgets.sql",
                    "003_research_workflows.sql",
                ):
                    migration = Path(__file__).with_name("migrations") / name
                    connection.execute(migration.read_text(encoding="utf-8"), prepare=False)
            self._checkpoint_connection = psycopg.connect(
                dsn,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=5,
                options=f"-csearch_path={schema}_checkpoints -cstatement_timeout=10000",
            )
            saver = PostgresSaver(
                self._checkpoint_connection,
                serde=JsonPlusSerializer(
                    allowed_msgpack_modules=[], allowed_json_modules=[], pickle_fallback=False
                ),
            )
            saver.setup()
            self._graph = NormalizationGraph(saver)
        except Exception as error:
            # Startup can fail after the pool exists, including a translated migration failure.
            if hasattr(self, "_pool"):
                self._pool.close()
            if hasattr(self, "_checkpoint_connection"):
                self._checkpoint_connection.close()
            if hasattr(self, "_log_filter"):
                logging.getLogger("psycopg.pool").removeFilter(self._log_filter)
            if isinstance(error, StorageConfigurationError):
                raise
            raise ResearchError(
                "DEPENDENCY_UNAVAILABLE", "Run storage is unavailable.", 503
            ) from None

    @contextmanager
    def _connection(self) -> Iterator[Connection[DictRow]]:
        """Never expose connection strings through driver failures or fall back to memory."""
        if self._closed:
            raise ResearchError("DEPENDENCY_UNAVAILABLE", "Run storage is closed.", 503)
        try:
            with self._pool.connection() as connection:
                yield connection
        except (psycopg.Error, PoolTimeout):
            raise ResearchError(
                "DEPENDENCY_UNAVAILABLE", "Run storage is unavailable.", 503
            ) from None

    def create(self, brief: ResearchBrief, key: str, principal: Principal) -> RunRecord:
        """The unique owner/key constraint arbitrates retries across processes and connections."""
        with self._connection() as connection, connection.transaction():
            run_id, created_at = uuid4(), datetime.now(UTC)
            inserted = connection.execute(
                "INSERT INTO research_runs (run_id,owner_issuer,owner_subject,idempotency_key,"
                "request_hash,request_json,status,graph_version,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,'RECEIVED',%s,%s,%s) "
                "ON CONFLICT (owner_issuer,owner_subject,idempotency_key) "
                "DO NOTHING RETURNING run_id",
                (
                    run_id,
                    principal.issuer,
                    principal.subject,
                    key,
                    request_hash(brief),
                    Jsonb(canonical_request(brief)),
                    self.graph_version,
                    created_at,
                    created_at,
                ),
            ).fetchone()
            if inserted:
                connection.execute(
                    "INSERT INTO research_state_events VALUES (%s,0,'RECEIVED',%s,NULL)",
                    (run_id, created_at),
                )
            row = connection.execute(
                "SELECT * FROM research_runs WHERE owner_issuer=%s AND owner_subject=%s "
                "AND idempotency_key=%s FOR UPDATE",
                (principal.issuer, principal.subject, key),
            ).fetchone()
            if row is None or row["request_json"] != canonical_request(brief):
                raise ResearchError(
                    "IDEMPOTENCY_CONFLICT", "This key belongs to a different request.", 409
                )
            self._inject("before_create_commit")
            return self._record(connection, row)

    def _owned(
        self,
        connection: Connection[DictRow],
        run_id: UUID,
        principal: Principal,
        *,
        lock: bool = False,
    ) -> DictRow:
        """Owner predicates prevent UUID guessing from revealing another user's research."""
        suffix = " FOR UPDATE" if lock else ""
        row = connection.execute(
            "SELECT * FROM research_runs WHERE run_id=%s AND owner_issuer=%s AND owner_subject=%s"
            + suffix,
            (run_id, principal.issuer, principal.subject),
        ).fetchone()
        if row is None:
            raise ResearchError("RUN_NOT_FOUND", "No run exists with that identifier.", 404)
        return row

    def _record(self, connection: Connection[DictRow], row: DictRow) -> RunRecord:
        """Return validated immutable domain data instead of leaking database row objects."""
        events = connection.execute(
            "SELECT status,created_at FROM research_state_events "
            "WHERE run_id=%s ORDER BY state_version",
            (row["run_id"],),
        ).fetchall()
        return RunRecord.model_validate(
            {
                **row["request_json"],
                "run_id": row["run_id"],
                "status": row["status"],
                "brief": row["normalized_brief"],
                "created_at": row["created_at"],
                "events": events,
                "mode": "local",
                "storage": "postgres",
            }
        )

    def get(self, run_id: UUID, principal: Principal) -> RunRecord:
        """Reading accepted state never schedules work or consults untrusted checkpoint input."""
        with self._connection() as connection, connection.transaction():
            row = self._owned(connection, run_id, principal, lock=True)
            if row["status"] == "BRIEF_NORMALIZED":
                self._verify_accepted(row)
            return self._record(connection, row)

    def _verify_accepted(self, row: DictRow) -> None:
        """Accepted results fail closed when their execution evidence is missing or altered."""
        checkpoint_id = self._graph.checkpoint_id(str(row["run_id"]))
        if not checkpoint_id or checkpoint_id != row["accepted_checkpoint_id"]:
            raise ResearchError(
                "CHECKPOINT_MISSING", "The accepted checkpoint is unavailable.", 503
            )
        brief, _ = self._graph.verify_finished(self._expected(row))
        if brief != row["normalized_brief"]:
            raise ResearchError("CHECKPOINT_CONFLICT", "The accepted brief is inconsistent.", 409)

    def _expected(self, row: DictRow) -> NormalizationState:
        """Bind graph replay to the immutable canonical input and current graph contract."""
        if row["graph_version"] != self.graph_version:
            raise ResearchError("CHECKPOINT_CONFLICT", "The graph version is incompatible.", 409)
        return NormalizationState(
            run_id=str(row["run_id"]),
            owner_issuer=row["owner_issuer"],
            owner_subject=row["owner_subject"],
            request_hash=row["request_hash"],
            graph_version=row["graph_version"],
            idea=row["request_json"]["idea"],
            status="RECEIVED",
            brief="",
        )

    def normalize(self, run_id: UUID, principal: Principal) -> RunRecord:
        """A short row lock protects publication; independent checkpoint commits remain explicit."""
        with self._connection() as connection, connection.transaction():
            row = self._owned(connection, run_id, principal, lock=True)
            expected = self._expected(row)
            if row["status"] == "BRIEF_NORMALIZED":
                self._verify_accepted(row)
                return self._record(connection, row)
            self._inject("before_checkpoint")
            brief, checkpoint_id = self._graph.finish(expected)
            self._inject("after_checkpoint")
            self._publish(connection, row, brief, checkpoint_id)
            self._inject("before_publication_commit")
            result = self._record(connection, self._owned(connection, run_id, principal))
        self._inject("after_publication_commit")
        return result

    def _publish(
        self, connection: Connection[DictRow], row: DictRow, brief: str, checkpoint_id: str
    ) -> None:
        """Publish the event and accepted checkpoint pointer in one canonical transaction."""
        timestamp = datetime.now(UTC)
        connection.execute(
            "UPDATE research_runs SET status='BRIEF_NORMALIZED',normalized_brief=%s,"
            "state_version=1,accepted_checkpoint_id=%s,updated_at=%s "
            "WHERE run_id=%s AND state_version=0",
            (brief, checkpoint_id, timestamp, row["run_id"]),
        )
        connection.execute(
            "INSERT INTO research_state_events VALUES (%s,1,'BRIEF_NORMALIZED',%s,%s)",
            (row["run_id"], timestamp, checkpoint_id),
        )

    def checkpoint_id(self, run_id: UUID, principal: Principal) -> str | None:
        """Evidence inspection is owner-gated before querying a checkpoint thread."""
        with self._connection() as connection:
            self._owned(connection, run_id, principal)
            return self._graph.checkpoint_id(str(run_id))

    def recover_pending(self, limit: int = 100) -> int:
        """Committed RECEIVED rows recover scheduling lost during process failure."""
        if not 1 <= limit <= 1000:
            raise ValueError("Recovery batch size must be between 1 and 1000")
        with self._connection() as connection:
            pending = connection.execute(
                "SELECT run_id,owner_issuer,owner_subject FROM research_runs "
                "WHERE status='RECEIVED' ORDER BY last_recovery_at NULLS FIRST,created_at LIMIT %s",
                (limit,),
            ).fetchall()
        recovered = 0
        for row in pending:
            self._record_attempt(row["run_id"])
            principal = Principal(row["owner_issuer"], row["owner_subject"], frozenset())
            try:
                self.normalize(row["run_id"], principal)
                recovered += 1
            except ResearchError as error:
                with self._connection() as connection:
                    connection.execute(
                        "UPDATE research_runs SET recovery_error_code=%s WHERE run_id=%s",
                        (error.code[:64], row["run_id"]),
                    )
        return recovered

    def _record_attempt(self, run_id: UUID) -> None:
        """Rotate failed work before retrying so one poison record cannot starve later runs."""
        with self._connection() as connection:
            connection.execute(
                "UPDATE research_runs SET recovery_attempts=recovery_attempts+1,"
                "last_recovery_at=%s,recovery_error_code=NULL WHERE run_id=%s",
                (datetime.now(UTC), run_id),
            )

    def _inject(self, stage: str) -> None:
        """An explicit test-only fault hook exercises actual cross-transaction failure windows."""
        if self.failpoint is not None:
            self.failpoint(stage)

    def ready(self) -> bool:
        """Readiness requires both canonical tables and the actual checkpointer connection."""
        try:
            with self._connection() as connection:
                connection.execute("SELECT run_id FROM research_runs LIMIT 1")
                self._graph.checkpoint_id(str(UUID(int=0)))
            return True
        except ResearchError:
            return False

    def close(self) -> None:
        """Release task-owned connections without changing persisted records or other databases."""
        if not self._closed:
            self._closed = True
            self._pool.close()
            self._checkpoint_connection.close()
            logging.getLogger("psycopg.pool").removeFilter(self._log_filter)
