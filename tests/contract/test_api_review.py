"""Independent HTTP/lifecycle probes exercise authorization and live blocking-work bounds."""

import asyncio
import json
import time
from threading import Event
from uuid import UUID

import anyio
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

from factorforge.api.app import create_app
from factorforge.api.dispatch import BlockingDispatcher
from factorforge.api.settings import Settings
from factorforge.auth.cognito import CognitoVerifier
from factorforge.domain.errors import ResearchError
from factorforge.orchestration.local_runs import LocalRunStore
from factorforge.orchestration.postgres_runs import PostgresRunStore


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    """Generate independent signing material for HTTP-boundary verification."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def dependencies(key: rsa.RSAPrivateKey) -> tuple[Settings, CognitoVerifier]:
    """Replace provider transport only; real RSA verification still determines the principal."""
    public = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    public.update(kid="review", use="sig", alg="RS256")
    config = Settings(
        mode="cognito",
        storage="postgres",
        dsn="unused-review-sentinel",
        region="us-east-1",
        pool_id="us-east-1_Review",
        client_id="reviewclient",
    )
    verifier = CognitoVerifier(
        region=config.region,
        pool_id=config.pool_id,
        client_id=config.client_id,
        fetch_jwks=lambda: json.dumps({"keys": [public]}).encode(),
    )
    return config, verifier


def bearer(key: rsa.RSAPrivateKey, scopes: str = "factorforge/read factorforge/create") -> str:
    """Only signed claims can grant the capabilities requested by each test."""
    now = int(time.time())
    return "Bearer " + jwt.encode(
        dict(
            iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Review",
            sub="review-user",
            token_use="access",
            client_id="reviewclient",
            scope=scopes,
            iat=now,
            exp=now + 300,
        ),
        key,
        algorithm="RS256",
        headers={"kid": "review"},
    )


@pytest.mark.parametrize("credential", [None, "Bearer invalid", "Basic invalid"])
def test_rejected_identity_never_reads_body(key: rsa.RSAPrivateKey, credential: str | None) -> None:
    """A missing or invalid identity is rejected before even a fragmented body is consumed."""
    config, verifier = dependencies(key)
    app = create_app(settings=config, store=LocalRunStore(), verifier=verifier)
    headers = [(b"host", b"api.example.test"), (b"content-type", b"application/json")]
    if credential is not None:
        headers.append((b"authorization", credential.encode()))
    scope: Scope = dict(
        type="http",
        asgi={"version": "3.0"},
        http_version="1.1",
        method="POST",
        scheme="https",
        path="/api/v1/research-runs",
        raw_path=b"/api/v1/research-runs",
        query_string=b"",
        root_path="",
        headers=headers,
        client=("192.0.2.1", 60000),
        server=("api.example.test", 443),
    )
    messages: list[Message] = []

    async def scenario() -> None:
        """Drive ASGI directly so an HTTP client's upload buffering cannot mask ordering."""

        async def receive() -> Message:
            """Any body read would violate the authentication-before-buffering boundary."""
            raise AssertionError("Unauthenticated request body was read")

        async def send(message: Message) -> None:
            """Capture only safe status and body fields from the application response."""
            messages.append(message)

        await app(scope, receive, send)

    anyio.run(scenario)
    assert messages[0]["status"] == 401


def test_capability_failure_does_not_reserve_receipt(key: rsa.RSAPrivateKey) -> None:
    """Denied creation cannot reserve a key that would conflict with the authorized retry."""
    config, verifier = dependencies(key)
    with TestClient(
        create_app(settings=config, store=LocalRunStore(), verifier=verifier)
    ) as client:
        headers = {
            "Authorization": bearer(key, "factorforge/read"),
            "Idempotency-Key": "review-key",
        }
        denied = client.post(
            "/api/v1/research-runs", json={"idea": "Denied original"}, headers=headers
        )
        assert denied.status_code == 403
        headers["Authorization"] = bearer(key)
        allowed = client.post(
            "/api/v1/research-runs", json={"idea": "Allowed replacement"}, headers=headers
        )
        assert allowed.status_code == 202
        identifier = allowed.json()["run_id"]
        no_read = client.get(
            f"/api/v1/research-runs/{identifier}",
            headers={"Authorization": bearer(key, "factorforge/create")},
        )
        assert no_read.status_code == 403


def test_ambiguous_credentials_keep_cors_trace_and_challenge(key: rsa.RSAPrivateKey) -> None:
    """Approved browsers must read typed duplicate-header failures without seeing credentials."""
    config, verifier = dependencies(key)
    with TestClient(
        create_app(settings=config, store=LocalRunStore(), verifier=verifier)
    ) as client:
        response = client.post(
            "/api/v1/research-runs",
            content=b"not-json",
            headers=[
                ("Authorization", bearer(key)),
                ("authorization", bearer(key)),
                ("Origin", config.allowed_origin),
            ],
        )
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.headers["access-control-allow-origin"] == config.allowed_origin
        assert response.headers["x-trace-id"] == response.json()["error"]["trace_id"]
        assert UUID(response.headers["x-trace-id"])
        assert bearer(key) not in response.text


def test_bad_startup_configuration_never_opens_injected_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An environment typo cannot become an implicit working local deployment."""
    monkeypatch.setenv("FACTORFORGE_MODE", "LOCAL")
    with TestClient(create_app(store=LocalRunStore())) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        result = client.post("/api/v1/research-runs", json={"idea": "Must be denied"})
        assert result.status_code == 503


def test_native_cancellation_does_not_release_live_thread_slot() -> None:
    """Native cancellation cannot admit work while the cancelled thread still runs."""
    started, finish, exited = Event(), Event(), Event()
    dispatcher = BlockingDispatcher(capacity=1)

    def blocked() -> None:
        """Hold a real worker past the awaiting task's native cancellation."""
        started.set()
        try:
            assert finish.wait(5)
        finally:
            exited.set()

    async def scenario() -> None:
        """asyncio.Task.cancel differs from AnyIO's cooperative cancellation scopes."""
        task = asyncio.create_task(dispatcher.run(blocked))
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(ResearchError) as error:
                await dispatcher.run(lambda: "must not overlap")
            assert error.value.code == "SERVICE_BUSY"
        finally:
            finish.set()
            while not exited.is_set():
                await asyncio.sleep(0)
        with anyio.fail_after(1):
            while True:
                try:
                    assert await dispatcher.run(lambda: "recovered") == "recovered"
                    break
                except ResearchError:
                    await asyncio.sleep(0)

    asyncio.run(scenario())


def test_exceptional_lifespan_exit_closes_owned_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Application teardown must close resources even when the lifespan body raises."""
    closed = Event()

    class OwnedStore(PostgresRunStore):
        """Observe the API's ownership lifecycle without touching an actual database."""

        def __init__(self, dsn: str) -> None:
            """No connection is needed to test cleanup responsibility."""

        def recover_pending(self, limit: int = 8) -> int:
            """Represent an empty recovery scan with no blocking work."""
            return 0

        def close(self) -> None:
            """Record closure rather than exposing any driver state."""
            closed.set()

    monkeypatch.setattr("factorforge.api.app.PostgresRunStore", OwnedStore)
    app = create_app(settings=Settings(mode="local", storage="postgres", dsn="unused"))

    async def scenario() -> None:
        """The lifecycle context must release resources along its exceptional path."""
        with pytest.raises(BaseExceptionGroup):
            async with app.router.lifespan_context(app):
                raise RuntimeError("Injected application shutdown failure")

    anyio.run(scenario)
    assert closed.is_set()


def test_pending_cancellation_returns_unused_capacity() -> None:
    """Cancellation before the shared worker limiter admits work must not leak a reservation."""
    dispatcher = BlockingDispatcher(capacity=1)
    invoked = Event()

    async def scenario() -> None:
        """Saturate the AnyIO worker limiter independently of application admission."""
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 1
        await limiter.acquire()
        task = asyncio.create_task(dispatcher.run(invoked.set))
        try:
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            limiter.release()
            limiter.total_tokens = previous
        assert not invoked.is_set()
        assert await dispatcher.run(lambda: "available") == "available"

    asyncio.run(scenario())


def test_shutdown_waits_for_native_cancelled_worker() -> None:
    """Resource teardown cannot race an abandoned thread that still owns database connections."""
    started, finish = Event(), Event()
    dispatcher = BlockingDispatcher(capacity=1)

    def operation() -> None:
        """Represent bounded database work that outlives its cancelled HTTP task."""
        started.set()
        assert finish.wait(5)

    async def scenario() -> None:
        """Drain remains pending and rejects admission until the actual worker completes."""
        work = asyncio.create_task(dispatcher.run(operation))
        while not started.is_set():
            await asyncio.sleep(0)
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
        closing = asyncio.create_task(dispatcher.close())
        second_close = asyncio.create_task(dispatcher.close())
        try:
            await asyncio.sleep(0)
            assert not closing.done()
            with pytest.raises(ResearchError):
                await dispatcher.run(lambda: "forbidden")
        finally:
            finish.set()
        await closing
        await second_close
        with pytest.raises(ResearchError):
            await dispatcher.run(lambda: "still forbidden")

    asyncio.run(scenario())


@pytest.mark.parametrize("capacity", [0, -1])
def test_invalid_worker_capacity_fails_configuration(capacity: int) -> None:
    """A permanently saturated worker limit must fail configuration rather than appear ready."""
    with pytest.raises(ValueError):
        BlockingDispatcher(capacity=capacity)


def test_native_startup_cancellation_closes_created_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """A driver constructor can finish after its startup waiter has been cancelled."""
    started, finish, closed = Event(), Event(), Event()

    class SlowStore(PostgresRunStore):
        """Represent delayed connection creation without using any real database."""

        def __init__(self, dsn: str) -> None:
            """Hold allocation until the API startup task is demonstrably cancelled."""
            started.set()
            assert finish.wait(5)

        def close(self) -> None:
            """The late-created resource still belongs to the cancelled lifespan."""
            closed.set()

    monkeypatch.setattr("factorforge.api.app.PostgresRunStore", SlowStore)
    app = create_app(settings=Settings(mode="local", storage="postgres", dsn="unused"))

    async def start() -> None:
        """Cancellation must prevent the lifespan from accepting requests."""
        async with app.router.lifespan_context(app):
            raise AssertionError("Cancelled startup entered service")

    async def scenario() -> None:
        """Shutdown waits for allocation and then closes its resource before propagating cancel."""
        task = asyncio.create_task(start())
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        try:
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert closed.is_set()

    asyncio.run(scenario())
