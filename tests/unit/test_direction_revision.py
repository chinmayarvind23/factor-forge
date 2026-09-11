"""Conflict-aware readings retain prior evidence and uncertainty without automatic edits."""

import json

import pytest
from pydantic import ValidationError
from test_monthly_admission import MemoryStore
from test_source_strategy import request as strategy_request

from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.errors import ResearchError
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from factorforge.retrieval.direction_review import DirectionObservation, DirectionReview
from factorforge.retrieval.direction_revision import DirectionRevisionRequest, revise_direction
from factorforge.retrieval.extraction import ExtractionResult, SourcePacket, SourcePage
from factorforge.retrieval.quote_first_revision import revise_direction_quote_first


def conflict(store: MemoryStore) -> DirectionRevisionRequest:
    """Original controlled observations disagree while retaining separate receipt identities."""
    return DirectionRevisionRequest(
        source=SourcePacket(
            paper_id="original",
            source_sha256="a" * 64,
            selected_strategy="score",
            pages=(
                SourcePage(
                    pdf_page=1,
                    artifact=store.put(b"Long low and short high.", media_type="text/plain"),
                ),
            ),
        ),
        extraction=ExtractionResult(
            status="extracted",
            observation=strategy_request().observation,
            record=store.put(b'{"attempt":"original"}', media_type="application/json"),
        ),
        review=DirectionReview(
            status="supported",
            observation=DirectionObservation(
                direction="long_low_short_high",
                quote="Long low and short high.",
                pdf_page=1,
                uncertainty=None,
            ),
            record=store.put(b'{"attempt":"review"}', media_type="application/json"),
        ),
    )


@pytest.mark.parametrize("quote_first", [False, True])
@pytest.mark.parametrize("outcome", ["supported", "uncertain", "invalid", "provider_failed"])
def test_revision_retains_context_and_one_new_observation(outcome: str, quote_first: bool) -> None:
    """The third reading can agree, abstain or fail citation checks without altering its inputs."""
    store = MemoryStore()
    request = conflict(store)
    before = request.canonical_bytes()
    calls = []

    class Provider:
        """Controlled output tests the new prompt boundary, not semantic model quality."""

        def generate(self, prompt: GenerationRequest, artifacts: ArtifactStore) -> GenerationResult:
            """Both prior observations must be visible and explicitly non-authoritative."""
            calls.append(prompt)
            payload = json.loads(prompt.user)
            assert payload["conflicting_observations"][
                "extraction"
            ] == request.extraction.model_dump(mode="json")
            assert payload["conflicting_observations"]["review"] == request.review.model_dump(
                mode="json"
            )
            if quote_first:
                assert "First copy an exact source passage" in prompt.system
                assert isinstance(prompt.response_schema["properties"], dict)
                assert sorted(prompt.response_schema["properties"])[0] == "citation"
            else:
                assert "Neither observation is authoritative" in prompt.system
            return GenerationResult(
                status="unavailable" if outcome == "provider_failed" else "success",
                record=artifacts.put(b"{}", media_type="application/json"),
                content=None
                if outcome == "provider_failed"
                else json.dumps(
                    {
                        "direction": None if outcome == "uncertain" else "long_low_short_high",
                        ("citation" if quote_first else "quote"): None
                        if outcome == "uncertain"
                        else (
                            "Invented quote" if outcome == "invalid" else "Long low and short high."
                        ),
                        "pdf_page": None if outcome == "uncertain" else 1,
                        "uncertainty": "Insufficient context" if outcome == "uncertain" else None,
                    }
                ),
            )

    execute = revise_direction_quote_first if quote_first else revise_direction
    result = execute(request, Provider(), store)
    assert result.status == outcome and len(calls) == 1
    assert request.canonical_bytes() == before
    record = json.loads(store.get(result.record))
    assert record["schema_version"] == (
        "direction-revision-quote-first-record-v1"
        if quote_first
        else "direction-revision-record-v1"
    )
    assert record["conflicting_observations"]["review"] == request.review.model_dump(mode="json")


@pytest.mark.parametrize("target", ["extraction", "review", "page"])
def test_corrupt_revision_inputs_precede_provider(target: str) -> None:
    """Prior receipt and raw source byte integrity must hold before another model call."""
    store = MemoryStore()
    request = conflict(store)
    ref = (
        request.source.pages[0].artifact
        if target == "page"
        else (request.extraction.record if target == "extraction" else request.review.record)
    )
    store.values[ref.sha256] = b"changed"

    class Provider:
        """An attempted call would demonstrate incorrect admission order."""

        def generate(self, prompt: GenerationRequest, artifacts: ArtifactStore) -> GenerationResult:
            """Reject any delivery after byte substitution."""
            raise AssertionError("provider must not run")

    with pytest.raises(ResearchError):
        revise_direction(request, Provider(), store)


def test_revision_requires_a_real_disagreement() -> None:
    """Copied agreement cannot be admitted as another revision attempt."""
    store = MemoryStore()
    request = conflict(store)
    initial = request.extraction.observation
    assert initial is not None
    agreeing = request.extraction.model_copy(
        update={
            "observation": initial.model_copy(
                update={"long_short_direction": "long_low_short_high"}
            )
        }
    )
    with pytest.raises(ValidationError):
        DirectionRevisionRequest.model_validate(request.model_copy(update={"extraction": agreeing}))
