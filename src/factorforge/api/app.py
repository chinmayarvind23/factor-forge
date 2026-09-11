"""Local walking skeleton; production operations fail closed until identity is configured."""

import os
from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from factorforge.api.body_limit import BodyLimitMiddleware
from factorforge.domain.errors import ResearchError
from factorforge.domain.research_brief import ResearchBrief, RunAccepted, RunRecord
from factorforge.orchestration.local_runs import LocalRunStore

LOCAL_ORIGIN = "http://127.0.0.1:3001"


def error_response(code: str, message: str, status_code: int, trace_id: str) -> JSONResponse:
    """Return the documented safe envelope without echoing arbitrary validation inputs."""
    return JSONResponse(
        status_code=status_code,
        headers={"X-Trace-ID": trace_id},
        content={
            "error": {"code": code, "message": message, "retryable": False, "trace_id": trace_id}
        },
    )


def create_app(*, local_mode: bool | None = None) -> FastAPI:
    """An explicit local mode cannot be mistaken for configured production authentication."""
    enabled = os.getenv("FACTORFORGE_MODE") == "local" if local_mode is None else local_mode
    store = LocalRunStore()
    application = FastAPI(title="FactorForge", version="0.1.0")
    application.add_middleware(BodyLimitMiddleware)

    @application.middleware("http")
    async def local_boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Deny remote/local-browser cross-origin use before any development-state operation."""
        trace_id = str(uuid4())
        request.state.trace_id = trace_id
        if request.url.path.startswith("/api/"):
            if not enabled:
                return error_response(
                    "NOT_CONFIGURED", "Research access is not configured.", 503, trace_id
                )
            local_client = request.client and request.client.host in {"127.0.0.1", "::1"}
            local_host = request.url.hostname in {"127.0.0.1", "localhost", "::1"}
            origin = request.headers.get("origin")
            if not local_client or not local_host or origin not in {None, LOCAL_ORIGIN}:
                return error_response(
                    "LOCAL_ACCESS_ONLY", "This service accepts local access only.", 403, trace_id
                )
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response

    @application.exception_handler(ResearchError)
    async def research_error(request: Request, error: ResearchError) -> JSONResponse:
        """Domain failures retain their stable code across transport implementations."""
        return error_response(error.code, error.message, error.status_code, request.state.trace_id)

    @application.exception_handler(RequestValidationError)
    async def input_error(request: Request, error: RequestValidationError) -> JSONResponse:
        """Rejected payloads are not echoed because ideas may contain private research text."""
        return error_response(
            "INPUT_INVALID",
            "Check the request fields and idempotency key.",
            422,
            request.state.trace_id,
        )

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Liveness does not depend on identity or imply that research can be accepted."""
        return {"status": "ok"}

    @application.get("/ready")
    async def ready() -> JSONResponse:
        """Disclose local ephemeral mode; unconfigured research access is not ready."""
        return JSONResponse(
            status_code=200 if enabled else 503,
            content={
                "status": "ready" if enabled else "not_configured",
                "mode": "local" if enabled else "disabled",
            },
        )

    @application.post("/api/v1/research-runs", status_code=202)
    async def create_run(
        brief: ResearchBrief,
        tasks: BackgroundTasks,
        idempotency_key: Annotated[
            str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
        ],
    ) -> RunAccepted:
        """Acknowledge a stable receipt before the lightweight local transition executes."""
        record = store.create(brief, idempotency_key)
        tasks.add_task(store.normalize, record.run_id)
        return RunAccepted(run_id=record.run_id)

    @application.get("/api/v1/research-runs/{run_id}")
    async def get_run(run_id: UUID) -> RunRecord:
        """Expose the stored event history so the browser never invents progress."""
        return store.get(run_id)

    # CORS wraps failures too, so the approved browser can read typed 413/503 responses.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[LOCAL_ORIGIN],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )
    return application


app = create_app()
