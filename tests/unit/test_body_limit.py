"""Exercise fragmented ASGI requests that an HTTP test client may coalesce."""

import asyncio
from collections import deque

from starlette.types import Message, Receive, Scope, Send

from factorforge.api.body_limit import BodyLimitMiddleware


def test_fragmented_body_preserves_bytes_and_disconnect() -> None:
    """Chunk boundaries cannot change JSON input and disconnect remains observable downstream."""

    async def scenario() -> None:
        """Drive the ASGI protocol directly to retain real multiple-frame behavior."""
        messages: deque[Message] = deque(
            [
                {"type": "http.request", "body": b"ab", "more_body": True},
                {"type": "http.request", "body": b"cd", "more_body": False},
                {"type": "http.disconnect"},
            ]
        )

        async def receive() -> Message:
            """Supply transport frames without involving a client-side buffer."""
            return messages.popleft()

        async def send(message: Message) -> None:
            """An allowed request must not produce an early rejection response."""
            raise AssertionError(message)

        async def application(scope: Scope, receive: Receive, send: Send) -> None:
            """Check the observable application contract rather than middleware internals."""
            assert await receive() == {"type": "http.request", "body": b"abcd", "more_body": False}
            assert await receive() == {"type": "http.disconnect"}

        await BodyLimitMiddleware(application)({"type": "http", "path": "/api/runs"}, receive, send)

    asyncio.run(scenario())


def test_disconnect_during_upload_never_invokes_application() -> None:
    """A partial upload must not allocate state or masquerade as a complete request."""

    async def scenario() -> None:
        """A closed transport exits before parsing or generating any response."""

        async def receive() -> Message:
            """Represent a client disconnect before completing a body."""
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            """There is no active response channel after the disconnect."""
            raise AssertionError(message)

        async def application(scope: Scope, receive: Receive, send: Send) -> None:
            """Any downstream work after upload failure would violate the boundary."""
            raise AssertionError("Application received incomplete upload")

        await BodyLimitMiddleware(application)({"type": "http", "path": "/api/runs"}, receive, send)

    asyncio.run(scenario())
