"""Keep blocking drivers and cryptography off the event loop with bounded admission."""

from collections.abc import Callable
from threading import BoundedSemaphore, Lock
from typing import TypeVar

import anyio

from factorforge.domain.errors import ResearchError

T = TypeVar("T")


class BlockingDispatcher:
    """Reject overload instead of accumulating an unbounded executor work queue."""

    def __init__(self, capacity: int = 8) -> None:
        """A process-local limit fits the bounded PostgreSQL pools and verifier cache."""
        if capacity < 1:
            raise ValueError("Dispatcher capacity must be positive.")
        self._capacity = capacity
        self._slots = BoundedSemaphore(capacity)
        self._admission = Lock()
        self._shutdown = Lock()
        self._closing = False

    async def run(self, operation: Callable[[], T]) -> T:
        """Keep admission reserved until worker completion, including native task cancellation."""
        with self._admission:
            if self._closing or not self._slots.acquire(blocking=False):
                raise ResearchError("SERVICE_BUSY", "The service is busy. Retry shortly.", 503)
        guard = Lock()
        started = False
        cancelled_before_start = False

        def invoke() -> T:
            """A cancelled queued callback must not run after its reservation was returned."""
            nonlocal started
            with guard:
                if cancelled_before_start:
                    raise ResearchError(
                        "WORK_CANCELLED", "Work was cancelled before starting.", 503
                    )
                started = True
            try:
                return operation()
            finally:
                self._slots.release()

        try:
            return await anyio.to_thread.run_sync(invoke)
        finally:
            # Native asyncio cancellation can abandon work despite AnyIO's default shielding.
            with guard:
                if not started:
                    cancelled_before_start = True
                    self._slots.release()

    async def close(self) -> None:
        """Drain cancelled workers before resource closure, rejecting any new admission."""
        with self._admission:
            self._closing = True

        def drain() -> None:
            """Owning every reservation proves no dispatched operation still uses the store."""
            with self._shutdown:
                for _ in range(self._capacity):
                    self._slots.acquire()
                for _ in range(self._capacity):
                    self._slots.release()

        await anyio.to_thread.run_sync(drain)
