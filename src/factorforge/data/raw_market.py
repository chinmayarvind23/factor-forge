"""Verified bounded source loading precedes raw-price and comparison-series interpretation."""

import json

from factorforge.data.artifacts import ArtifactStore, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.domain.raw_market import IntervalSource, RawMarketSource

MAX_SOURCE_BYTES = 8 * 1024 * 1024


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Duplicate fields never replace another claimed value before contract validation."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate raw source member")
        result[key] = value
    return result


def _nonfinite(token: str) -> object:
    """JSON nonfinite extensions cannot enter exact source accounting."""
    raise ValueError("Nonfinite raw source member")


def _source[Source: Contract](
    reference: ArtifactRef, store: ArtifactStore, model: type[Source], limits: dict[str, int]
) -> Source:
    """Check bytes, nesting and row counts before recursive typed date and amount parsing."""
    reference = ArtifactRef.model_validate(reference)
    if reference.media_type != "application/json" or reference.size_bytes > MAX_SOURCE_BYTES:
        raise ResearchError("RAW_SOURCE_LIMIT", "Raw source exceeds its declared limit.", 422)
    raw = store.get(reference)
    verify_bytes(raw, reference)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
        if not isinstance(value, dict):
            raise ValueError("Raw source requires an object")
        for name, limit in limits.items():
            rows = value.get(name)
            if not isinstance(rows, list) or len(rows) > limit:
                raise ValueError("Raw source inventory exceeds its bound")
        pending = [(value, 0)]
        while pending:
            node, depth = pending.pop()
            if depth > 16:
                raise ValueError("Raw source nesting exceeds its bound")
            if isinstance(node, dict):
                pending.extend((child, depth + 1) for child in node.values())
            elif isinstance(node, list):
                pending.extend((child, depth + 1) for child in node)
        return model.model_validate_json(raw, strict=True)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ResearchError(
            "RAW_SOURCE_INVALID", "Raw source is invalid for its declared role.", 422
        ) from None


def load_market(reference: ArtifactRef, store: ArtifactStore) -> RawMarketSource:
    """Load exact raw quotes, action coverage and explicit original-fixture loan terms."""
    return _source(
        reference,
        store,
        RawMarketSource,
        {"security_ids": 8, "quotes": 8192, "actions": 2048, "borrow_grants": 2048},
    )


def load_intervals(reference: ArtifactRef, store: ArtifactStore) -> IntervalSource:
    """Load supplied benchmark and risk-free intervals without imputing a missing observation."""
    return _source(reference, store, IntervalSource, {"rows": 1022})
