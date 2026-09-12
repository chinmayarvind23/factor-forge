"""Opt-in local OTel export keeps trace plumbing separate from authoritative run evidence."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Tracer

_LOCAL_TRACER: ContextVar[Tracer | None] = ContextVar("factorforge_tracer", default=None)


def tracer() -> Tracer:
    """Use a scoped operator exporter or the embedding application's configured OTel provider."""
    return _LOCAL_TRACER.get() or trace.get_tracer("factorforge")


@contextmanager
def use_tracer(value: Tracer) -> Iterator[None]:
    """Context-local injection preserves parentage without replacing a process-global provider."""
    token = _LOCAL_TRACER.set(value)
    try:
        yield
    finally:
        _LOCAL_TRACER.reset(token)


@contextmanager
def local_trace(path: Path | None) -> Iterator[None]:
    """Create a new JSONL trace file, flush on exit and refuse accidental overwrite.

    This opt-in diagnostic sink contains only instrumented metadata. It is not a durable
    operation ledger, and exporter failure must not trigger a second model/experiment call.
    """
    if path is None:
        yield
        return
    with path.open("x", encoding="utf-8") as output:
        provider = TracerProvider(resource=Resource({"service.name": "factorforge"}))
        provider.add_span_processor(
            SimpleSpanProcessor(
                ConsoleSpanExporter(
                    out=output, formatter=lambda span: span.to_json(indent=None) + "\n"
                )
            )
        )
        try:
            with use_tracer(provider.get_tracer("factorforge")):
                yield
        finally:
            provider.shutdown()
