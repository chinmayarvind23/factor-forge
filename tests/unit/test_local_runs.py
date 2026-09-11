"""Reference checks for bounded state allocation and legal local transitions."""

import pytest

from factorforge.domain.errors import ResearchError
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.local_runs import LocalRunStore


def test_capacity_never_evicts_existing_receipt() -> None:
    """Refusing new work preserves idempotency when the development store reaches its limit."""
    store = LocalRunStore(capacity=1)
    brief = ResearchBrief(idea="Investigate momentum")
    record = store.create(brief, "first")
    with pytest.raises(ResearchError, match="full") as error:
        store.create(brief, "second")
    assert error.value.code == "LOCAL_CAPACITY"
    assert store.create(brief, "first").run_id == record.run_id


def test_normalization_is_single_transition() -> None:
    """A replayed background task cannot duplicate events or reset an advanced record."""
    store = LocalRunStore()
    record = store.create(ResearchBrief(idea="Investigate momentum"), "first")
    assert record.status == "RECEIVED"
    store.normalize(record.run_id)
    store.normalize(record.run_id)
    normalized = store.get(record.run_id)
    assert len(normalized.events) == 2
    assert normalized.status == "BRIEF_NORMALIZED"
    assert normalized.events[1].created_at >= normalized.events[0].created_at
