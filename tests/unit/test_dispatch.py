"""Admission limits cap live blocking work without building a deferred queue."""

from threading import Event

import anyio
import pytest

from factorforge.api.dispatch import BlockingDispatcher
from factorforge.domain.errors import ResearchError


def test_overload_is_rejected_and_capacity_recovers() -> None:
    """A saturated worker remains occupied until its underlying operation actually finishes."""
    started, finish = Event(), Event()
    dispatcher = BlockingDispatcher(capacity=1)

    def block() -> None:
        """Hold real thread work so the competing call observes genuine saturation."""
        started.set()
        assert finish.wait(timeout=5)

    async def scenario() -> None:
        """The refused call must not consume a slot after the first operation completes."""
        async with anyio.create_task_group() as group:
            group.start_soon(dispatcher.run, block)
            while not started.is_set():
                await anyio.sleep(0)
            try:
                with pytest.raises(ResearchError) as failure:
                    await dispatcher.run(lambda: "unreachable")
                assert failure.value.code == "SERVICE_BUSY"
            finally:
                finish.set()
        assert await dispatcher.run(lambda: "available") == "available"

    anyio.run(scenario)
