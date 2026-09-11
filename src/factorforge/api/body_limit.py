"""Bound request buffering before JSON decoding, including chunked requests."""

from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyLimitMiddleware:
    """A bounded prebuffer avoids trusting Content-Length or allocating an unlimited JSON body."""

    def __init__(self, app: ASGIApp, max_bytes: int = 16384) -> None:
        """The limit permits the documented idea and budgets while bounding each local request."""
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Replay validated bytes once; retain the original receiver for disconnect notification."""
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        length = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            length += len(chunk)
            if length > self.max_bytes:
                await self.reject(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        buffered: bytes | None = b"".join(chunks)

        async def replay() -> Message:
            """The application receives identical bytes without re-reading the network stream."""
            nonlocal buffered
            if buffered is not None:
                body, buffered = buffered, None
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Oversized requests fail without including potentially sensitive request content."""
        trace_id = scope.get("state", {}).get("trace_id", str(uuid4()))
        response = JSONResponse(
            status_code=413,
            headers={"X-Trace-ID": trace_id},
            content={
                "error": {
                    "code": "REQUEST_TOO_LARGE",
                    "message": "Request exceeds 16384 bytes.",
                    "retryable": False,
                    "trace_id": trace_id,
                }
            },
        )
        await response(scope, receive, send)
