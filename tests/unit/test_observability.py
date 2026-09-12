"""Real SDK spans preserve parentage and references without copying provider content."""

import json
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from opentelemetry.trace import StatusCode
from test_ollama import FixtureTransport, generation_request, response, valid_reply

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.observability import local_trace, tracer
from factorforge.providers.ollama import OllamaProvider


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Use plain owned directories to avoid Windows pytest-current reparse points."""
    with TemporaryDirectory(prefix="factorforge-trace-") as directory:
        yield Path(directory)


@pytest.mark.parametrize("reason,outcome", [("stop", "success"), ("length", "truncated")])
def test_provider_spans_link_evidence_and_parent_without_content(
    tmp_path: Path, reason: str, outcome: str
) -> None:
    """The SDK export contains actual call identity, not prompts, answers or fabricated cost."""
    destination = tmp_path / "trace.jsonl"
    transport = FixtureTransport(response({**valid_reply(), "done_reason": reason}))
    request = generation_request().model_copy(update={"system": "PRIVATE_PROMPT_CANARY"})
    with local_trace(destination), tracer().start_as_current_span("research_execution"):
        result = OllamaProvider(transport=transport).generate(
            request, LocalArtifactStore(tmp_path / "objects")
        )
    raw = destination.read_text()
    spans = [json.loads(line) for line in raw.splitlines()]
    assert len(spans) == 2
    child, parent = spans
    assert child["parent_id"] == parent["context"]["span_id"]
    assert child["context"]["trace_id"] == parent["context"]["trace_id"]
    assert child["attributes"]["factorforge.provider_record.sha256"] == result.record.sha256
    assert child["attributes"]["factorforge.provider.outcome"] == outcome
    assert child["status"]["status_code"] == (
        "UNSET" if outcome == "success" else StatusCode.ERROR.name
    )
    assert "gen_ai.usage.input_tokens" in child["attributes"]
    assert "PRIVATE_PROMPT_CANARY" not in raw and '"billing"' not in raw
    assert len([call for call in transport.calls if call.url.path == "/api/chat"]) == 1
    with pytest.raises(FileExistsError), local_trace(destination):
        pass


def test_trace_scope_restores_previous_tracer(tmp_path: Path) -> None:
    """Leaving a scoped exporter cannot redirect later application traces into a closed file."""
    original = tracer()
    with local_trace(tmp_path / "trace.jsonl"):
        assert tracer() is not original
    assert type(tracer()) is type(original)
