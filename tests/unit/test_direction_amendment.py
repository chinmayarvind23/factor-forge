"""Amendment creates a distinct draft and cannot change unrelated economic choices."""

import pytest
from test_direction_revision import conflict
from test_monthly_admission import MemoryStore
from test_source_strategy import request as strategy_request

from factorforge.domain.errors import ResearchError
from factorforge.domain.raw_strategy import RawStrategySpec
from factorforge.factors.direction_amendment import DirectionAmendmentRequest, amend_direction
from factorforge.factors.source_strategy import SourceStrategyRequest, compile_source_strategy
from factorforge.retrieval.direction_review import DirectionObservation, DirectionReview


def amendment_request(store: MemoryStore) -> DirectionAmendmentRequest:
    """Bind the original fixture compiler request to the exact extraction record."""
    prior = conflict(store)
    original = strategy_request()
    environment = RawStrategySpec.model_validate(
        original.environment.model_copy(
            update={"source_refs": (*original.environment.source_refs, prior.extraction.record)}
        )
    )
    draft = compile_source_strategy(
        SourceStrategyRequest(
            environment=environment,
            reviewed_formation_rule=original.reviewed_formation_rule,
            observation=original.observation,
        )
    )
    return DirectionAmendmentRequest(
        original=draft,
        conflict=prior,
        resolution=DirectionReview(
            status="supported",
            observation=prior.review.observation,
            record=store.put(b'{"attempt":"revision"}', media_type="application/json"),
        ),
    )


def test_amendment_changes_only_direction_and_lineage() -> None:
    """New identity preserves formula, capital-independent environment and all original evidence."""
    store = MemoryStore()
    request = amendment_request(store)
    original_bytes = request.original.canonical_bytes()
    result = amend_direction(request)
    assert result.reason is None and result.draft is not None and result.draft.strategy is not None
    revised = result.draft
    assert revised.strategy is not None
    assert revised.request.observation.long_short_direction == "long_low_short_high"
    expected = request.original.request.observation.model_dump()
    expected["long_short_direction"] = "long_low_short_high"
    assert revised.request.observation.model_dump() == expected
    before = request.original.request.environment.model_dump()
    after = revised.request.environment.model_dump()
    before.pop("source_refs")
    after.pop("source_refs")
    assert before == after
    assert request.conflict.extraction.record in revised.strategy.source_refs
    assert request.conflict.review.record in revised.strategy.source_refs
    assert request.resolution.record in revised.strategy.source_refs
    assert request.original.canonical_bytes() == original_bytes
    assert request.original.strategy is not None
    assert revised.strategy.factor_id != request.original.strategy.factor_id
    assert amend_direction(request) == result


@pytest.mark.parametrize("outcome", ["uncertain", "invalid", "provider_failed", "opposite"])
def test_unconfirmed_revision_holds_amendment(outcome: str) -> None:
    """The compiler cannot silently prefer a conflicting or unusable third observation."""
    store = MemoryStore()
    request = amendment_request(store)
    if outcome == "opposite":
        resolution = DirectionReview(
            status="supported",
            record=request.resolution.record,
            observation=DirectionObservation(
                direction="long_high_short_low", quote="Other reading", pdf_page=1, uncertainty=None
            ),
        )
    else:
        resolution = DirectionReview.model_validate(
            {
                "status": outcome,
                "record": request.resolution.record,
                "observation": DirectionObservation(
                    direction=None, quote=None, pdf_page=None, uncertainty="Unclear source"
                )
                if outcome == "uncertain"
                else None,
            }
        )
    actual = amend_direction(request.model_copy(update={"resolution": resolution}))
    assert actual.draft is None and actual.reason is not None


def test_other_extraction_cannot_amend_original_draft() -> None:
    """An unrelated retained record cannot borrow a compiled draft's execution environment."""
    store = MemoryStore()
    request = amendment_request(store)
    changed = request.conflict.model_copy(
        update={
            "extraction": request.conflict.extraction.model_copy(
                update={"record": store.put(b'{"other":true}', media_type="application/json")}
            )
        }
    )
    with pytest.raises(ResearchError) as error:
        amend_direction(request.model_copy(update={"conflict": changed}))
    assert error.value.code == "DIRECTION_AMENDMENT_INVALID"
