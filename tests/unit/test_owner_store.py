"""The development adapter shares the same owner boundary as durable storage."""

import pytest

from factorforge.auth.principal import Principal
from factorforge.domain.errors import ResearchError
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.local_runs import LocalRunStore


def test_owner_isolation_and_receipt_namespace() -> None:
    """A known UUID and reused key cannot cross issuer or subject boundaries."""
    store = LocalRunStore()
    owners = [
        Principal("pool-a", "user", frozenset()),
        Principal("pool-b", "user", frozenset()),
        Principal("pool-a", "other", frozenset()),
    ]
    brief = ResearchBrief(idea="Investigate momentum")
    records = [store.create(brief, "same-key", owner) for owner in owners]
    assert len({record.run_id for record in records}) == 3
    for foreign in owners[1:]:
        with pytest.raises(ResearchError) as failure:
            store.get(records[0].run_id, foreign)
        assert failure.value.status_code == 404
        with pytest.raises(ResearchError):
            store.normalize(records[0].run_id, foreign)
    assert store.normalize(records[0].run_id, owners[0]).status == "BRIEF_NORMALIZED"
