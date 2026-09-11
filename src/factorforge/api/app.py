"""Research API with explicit identity and storage modes and bounded durable recovery."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

import anyio
from fastapi import BackgroundTasks, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from factorforge.api.body_limit import BodyLimitMiddleware
from factorforge.api.dispatch import BlockingDispatcher
from factorforge.api.settings import Settings
from factorforge.auth.cognito import MAX_TOKEN_BYTES, CognitoVerifier, unauthorized
from factorforge.auth.principal import LOCAL_PRINCIPAL, Principal
from factorforge.domain.errors import ResearchError
from factorforge.domain.research_brief import ResearchBrief, RunAccepted, RunRecord
from factorforge.orchestration.local_runs import LocalRunStore
from factorforge.orchestration.postgres_runs import PostgresRunStore

logger = logging.getLogger(__name__)
RunStore = LocalRunStore | PostgresRunStore


def error_response(code: str, message: str, status_code: int, trace_id: str) -> JSONResponse:
    """Expose stable codes without raw tokens, request bodies or dependency diagnostics."""
    return JSONResponse(
        status_code=status_code,
        headers={
            "X-Trace-ID": trace_id,
            **({"WWW-Authenticate": "Bearer"} if status_code == 401 else {}),
        },
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": status_code == 503,
                "trace_id": trace_id,
            }
        },
    )


def create_app(
    *,
    local_mode: bool | None = None,
    settings: Settings | None = None,
    store: RunStore | None = None,
    verifier: CognitoVerifier | None = None,
) -> FastAPI:
    """Explicit injected dependencies support boundary tests without production fallback."""
    configuration_error = False
    try:
        config = settings or (
            Settings(mode="local" if local_mode else "disabled")
            if local_mode is not None
            else Settings.from_environment()
        )
        identity = verifier
        if config.mode == "cognito" and identity is None:
            identity = CognitoVerifier(
                region=config.region,
                pool_id=config.pool_id,
                client_id=config.client_id,
                audience=config.audience,
            )
    except ValueError:
        config, identity, configuration_error = Settings(), None, True
    active_store = store
    dispatch = BlockingDispatcher()

    async def recovery_loop(durable: PostgresRunStore) -> None:
        """Durable RECEIVED rows survive lost scheduling; failures remain pending for retry."""
        while True:
            try:
                await dispatch.run(lambda: durable.recover_pending(limit=8))
            except ResearchError as error:
                logger.warning("Research recovery unavailable: %s", error.code)
            await anyio.sleep(2)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Database startup failures keep health available without substituting memory storage."""
        nonlocal active_store
        owned = active_store is None

        def initialize_store() -> None:
            """Retain ownership even if cancellation abandons the constructor's awaited result."""
            nonlocal active_store
            active_store = (
                PostgresRunStore(config.dsn or "")
                if config.storage == "postgres"
                else LocalRunStore()
            )

        try:
            if owned and config.mode != "disabled":
                try:
                    await dispatch.run(initialize_store)
                except (ResearchError, ValueError):
                    logger.warning("Research storage initialization failed.")
            async with anyio.create_task_group() as group:
                if isinstance(active_store, PostgresRunStore):
                    group.start_soon(recovery_loop, active_store)
                try:
                    yield
                finally:
                    group.cancel_scope.cancel()
        finally:
            with anyio.CancelScope(shield=True):
                await dispatch.close()
                if owned and isinstance(active_store, PostgresRunStore):
                    await anyio.to_thread.run_sync(active_store.close)

    application = FastAPI(title="FactorForge", version="0.1.0", lifespan=lifespan)
    application.add_middleware(BodyLimitMiddleware)

    @application.middleware("http")
    async def access_boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Verify identity before request validation and preserve the local loopback boundary."""
        trace_id = str(uuid4())
        request.state.trace_id = trace_id
        if request.url.path.startswith("/api/"):
            try:
                if config.mode == "disabled" or configuration_error:
                    raise ResearchError("NOT_CONFIGURED", "Research access is not configured.", 503)
                origin = request.headers.get("origin")
                if config.mode == "local":
                    local_client = request.client and request.client.host in {"127.0.0.1", "::1"}
                    local_host = request.url.hostname in {"127.0.0.1", "localhost", "::1"}
                    if (
                        not local_client
                        or not local_host
                        or origin not in {None, config.allowed_origin}
                    ):
                        raise ResearchError(
                            "LOCAL_ACCESS_ONLY", "This service accepts local access only.", 403
                        )
                    principal = LOCAL_PRINCIPAL
                else:
                    if origin not in {None, config.allowed_origin}:
                        raise ResearchError(
                            "ORIGIN_DENIED", "This browser origin is not permitted.", 403
                        )
                    headers = request.headers.getlist("authorization")
                    if len(headers) != 1 or len(headers[0]) > MAX_TOKEN_BYTES + 7:
                        raise unauthorized()
                    scheme, separator, token = headers[0].partition(" ")
                    if scheme.lower() != "bearer" or not separator or not token or " " in token:
                        raise unauthorized()
                    if identity is None:
                        raise ResearchError("NOT_CONFIGURED", "Identity is not configured.", 503)
                    principal = await dispatch.run(lambda: identity.verify(token))
                request.state.principal = principal
                if active_store is None:
                    raise ResearchError(
                        "STORAGE_UNAVAILABLE", "Research storage is unavailable.", 503
                    )
            except ResearchError as error:
                return error_response(error.code, error.message, error.status_code, trace_id)
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response

    @application.exception_handler(ResearchError)
    async def research_error(request: Request, error: ResearchError) -> JSONResponse:
        """Domain failures keep a stable public envelope across storage implementations."""
        return error_response(error.code, error.message, error.status_code, request.state.trace_id)

    @application.exception_handler(RequestValidationError)
    async def input_error(request: Request, error: RequestValidationError) -> JSONResponse:
        """Ideas may contain private research; never echo rejected inputs in diagnostics."""
        return error_response(
            "INPUT_INVALID",
            "Check the request fields and idempotency key.",
            422,
            request.state.trace_id,
        )

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Liveness remains independent of identity and database availability."""
        return {"status": "ok"}

    @application.get("/ready")
    async def ready() -> JSONResponse:
        """A configured durable adapter must actually reach storage to report readiness."""
        available = config.mode != "disabled" and active_store is not None
        if available and isinstance(active_store, PostgresRunStore):
            try:
                available = await dispatch.run(active_store.ready)
            except ResearchError:
                available = False
        return JSONResponse(
            status_code=200 if available else 503,
            content={
                "status": "ready" if available else "not_ready",
                "mode": config.mode,
                "storage": config.storage,
            },
        )

    async def normalize_local(run_id: UUID, principal: Principal) -> None:
        """Pure development work uses the same admission limit as database operations."""
        if isinstance(active_store, LocalRunStore):
            try:
                await dispatch.run(lambda: active_store.normalize(run_id, principal))
            except ResearchError as error:
                logger.warning("Local normalization unavailable: %s", error.code)

    @application.post("/api/v1/research-runs", status_code=202)
    async def create_run(
        brief: ResearchBrief,
        request: Request,
        tasks: BackgroundTasks,
        idempotency_key: Annotated[
            str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
        ],
    ) -> RunAccepted:
        """Commit a stable owner-scoped receipt before acknowledging or scheduling work."""
        principal: Principal = request.state.principal
        principal.require("create_run")
        current = active_store
        assert current is not None
        record = await dispatch.run(lambda: current.create(brief, idempotency_key, principal))
        if isinstance(current, LocalRunStore):
            tasks.add_task(normalize_local, record.run_id, principal)
        return RunAccepted(run_id=record.run_id)

    @application.get("/api/v1/research-runs/{run_id}")
    async def get_run(run_id: UUID, request: Request) -> RunRecord:
        """Reads expose only accepted owner-scoped state and never execute graph work."""
        principal: Principal = request.state.principal
        principal.require("read_own_run")
        current = active_store
        assert current is not None
        record = await dispatch.run(lambda: current.get(run_id, principal))
        return record.model_copy(update={"mode": config.mode})

    # CORS wraps failures so the approved browser can read typed auth/body/storage errors.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[config.allowed_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key", "Authorization"],
    )
    return application


app = create_app()
