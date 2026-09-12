"""Multi-source synthesis must select reviewed parents, cite real pages and preserve weights."""

import json
from typing import Any

import pytest
from test_monthly_admission import original_strategy

from factorforge.data.artifacts import ArtifactStore
from factorforge.factors.hybrid import publish
from factorforge.lineage.closure import verify_closure
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from factorforge.retrieval.direction_review import DirectionObservation, DirectionReview
from factorforge.retrieval.extraction import SourcePacket, SourcePage
from factorforge.retrieval.synthesis import SynthesisCandidate, SynthesisRequest, synthesize


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "abstain",
        "unknown_parent",
        "invented_quote",
        "weights",
        "duplicate",
        "malformed",
        "blank_quote",
    ],
)
def test_synthesis_accepts_only_cited_coherent_proposals(case: str) -> None:
    """Original controlled responses isolate source/weight admission from model accuracy."""
    strategy, store = original_strategy()
    text = "Rank by score. Long high score and short low score."
    page = store.put(text.encode(), media_type="text/plain")
    review = DirectionReview(
        status="supported",
        observation=DirectionObservation(
            direction="long_high_short_low",
            quote=text,
            pdf_page=1,
            uncertainty=None,
        ),
        record=store.put(b"{}", media_type="application/json"),
    )
    candidates = tuple(
        SynthesisCandidate(
            source=SourcePacket(
                paper_id=identifier,
                source_sha256=page.sha256,
                selected_strategy="Original " + identifier,
                pages=(SourcePage(pdf_page=1, artifact=page),),
            ),
            strategy=strategy.model_copy(update={"factor_id": identifier}),
            review=review,
        )
        for identifier in ("source-one", "source-two")
    )
    request = SynthesisRequest(idea="Combine two source hypotheses", candidates=candidates)
    wire: dict[str, Any] = dict(
        status="proposed",
        rationale="Evaluate an equal-weight research blend.",
        abstention=None,
        allocations=[
            dict(paper_id=row.source.paper_id, numerator=1, denominator=2, quote=text, pdf_page=1)
            for row in candidates
        ],
    )
    if case == "abstain":
        wire.update(
            status="abstained", allocations=[], abstention="No complementary mechanism established."
        )
    elif case == "unknown_parent":
        wire["allocations"][0]["paper_id"] = "invented"
    elif case == "invented_quote":
        wire["allocations"][0]["quote"] = "Guaranteed profit."
    elif case == "weights":
        wire["allocations"][0]["numerator"] = 2
    elif case == "duplicate":
        wire["allocations"][0]["paper_id"] = "source-two"
    elif case == "blank_quote":
        wire["allocations"][0]["quote"] = "   "
    calls = []

    class Provider:
        """Return one controlled observation and preserve the actual request for inspection."""

        def generate(self, prompt: GenerationRequest, artifacts: ArtifactStore) -> GenerationResult:
            """The synthesizer gets text delivery only, without access to execution tools."""
            calls.append(prompt)
            return GenerationResult(
                status="success",
                content="{invalid" if case == "malformed" else json.dumps(wire),
                record=artifacts.put(b"{}", media_type="application/json"),
            )

    result = synthesize(request, Provider(), store)
    assert len(calls) == 1 and calls[0].model == "qwen3:8b"
    assert result.status == (
        "proposed" if case == "valid" else "abstained" if case == "abstain" else "invalid"
    )
    assert (result.proposal is not None) == (case == "valid")
    assert result.record.sha256 in store.values
    assert verify_closure(publish(result, store), store)
