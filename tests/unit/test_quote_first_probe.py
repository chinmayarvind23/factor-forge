"""Experimental schema and receipt guards retain a single explicit provider attempt."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_direction_revision import conflict
from test_monthly_admission import MemoryStore

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from factorforge.retrieval.direction_review import DirectionReview
from factorforge.retrieval.direction_revision import DirectionRevisionRequest
from factorforge.retrieval.extraction import TextProvider
from factorforge.retrieval.quote_first_revision import revise_direction_quote_first
from infra.research.probe_revision import main


def test_source_only_probe_retains_hidden_conflict_in_evidence() -> None:
    """Prior model judgments remain auditable while the experimental prompt omits them."""
    store = MemoryStore()
    request = conflict(store)

    class Provider:
        """Controlled delivery verifies the intended context boundary."""

        def generate(self, prompt: GenerationRequest, artifacts: ArtifactStore) -> GenerationResult:
            """No initial direction label or prior record may anchor this model request."""
            payload = json.loads(prompt.user)
            assert set(payload) == {"selected_strategy", "pages"}
            assert "two supplied model observations" not in prompt.system
            return GenerationResult(
                status="success",
                record=artifacts.put(b"{}", media_type="application/json"),
                content=json.dumps(
                    {
                        "citation": "Long low and short high.",
                        "pdf_page": 1,
                        "direction": "long_low_short_high",
                        "uncertainty": None,
                    }
                ),
            )

    result = revise_direction_quote_first(request, Provider(), store, context="source_only")
    assert result.status == "supported"
    record = json.loads(store.get(result.record))
    assert record["schema_version"] == "direction-revision-source-only-record-v1"
    assert record["conflicting_observations"]["extraction"] == request.extraction.model_dump(
        mode="json"
    )


@pytest.mark.parametrize("both", [False, True])
def test_quote_first_rejects_legacy_or_ambiguous_field(both: bool) -> None:
    """The candidate profile cannot silently accept two competing citation fields."""
    store = MemoryStore()
    request = conflict(store)

    class Provider:
        """Controlled fields test schema acceptance rather than model accuracy."""

        def generate(self, prompt: GenerationRequest, artifacts: ArtifactStore) -> GenerationResult:
            """Return either the old field or both field names, each outside the new schema."""
            wire: dict[str, object] = {
                "direction": "long_low_short_high",
                "quote": "Long low and short high.",
                "pdf_page": 1,
                "uncertainty": None,
            }
            if both:
                wire["citation"] = "Long low and short high."
            return GenerationResult(
                status="success",
                content=json.dumps(wire),
                record=artifacts.put(b"{}", media_type="application/json"),
            )

    assert revise_direction_quote_first(request, Provider(), store).status == "invalid"


def test_probe_receipt_prevents_accidental_second_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """An existing result path stops a repeated probe before another provider call."""
    memory = MemoryStore()
    request = conflict(memory)
    calls = []

    def generate(
        retained: DirectionRevisionRequest,
        provider: TextProvider,
        store: ArtifactStore,
        *,
        context: str = "conflict",
    ) -> DirectionReview:
        """The controlled probe preserves a typed observation for receipt publication."""
        calls.append(retained)
        return retained.review

    monkeypatch.setattr("infra.research.probe_revision.revise_direction_quote_first", generate)
    with TemporaryDirectory() as directory:
        root = Path(directory)
        store = LocalArtifactStore(root / "objects")
        for ref in (
            request.extraction.record,
            request.review.record,
            request.source.pages[0].artifact,
        ):
            assert store.put(memory.get(ref), media_type=ref.media_type) == ref
        path = root / "request.json"
        path.write_bytes(request.canonical_bytes())
        output = root / "receipt.jsonl"
        monkeypatch.setattr(
            "sys.argv",
            [
                "probe",
                "--request",
                str(path),
                "--artifacts",
                str(root / "objects"),
                "--output",
                str(output),
            ],
        )
        main()
        before = output.read_bytes()
        rows = [json.loads(row) for row in before.splitlines()]
        assert [row["status"] for row in rows] == ["started", "recorded"]
        with pytest.raises(FileExistsError):
            main()
        assert output.read_bytes() == before and len(calls) == 1
