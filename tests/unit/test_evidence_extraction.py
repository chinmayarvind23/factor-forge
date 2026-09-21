"""Evidence-first observations require exact source quotations for asserted strategy fields."""

import json

import pytest

from factorforge.retrieval.evidence_first import parse_evidence


@pytest.mark.parametrize(
    "change", ["valid", "invented_quote", "missing_support", "wrong_page", "duplicate_key"]
)
def test_literal_support_boundary(change: str) -> None:
    """Quoted text is checked against the supplied physical page before admitting an observation."""
    observation = dict(
        status="extracted",
        refusal_reason=None,
        refusal_category=None,
        formula="x",
        required_inputs=["x"],
        long_short_direction=None,
        bucket_count=None,
        weighting=None,
        lookback_months=None,
        holding_months=None,
        rebalance_frequency=None,
        formation_lag_months=None,
        formation_rule=None,
        source_pages=[1],
    )
    quote = dict(fields=["formula", "required_inputs"], pdf_page=1, quote="Sort on x.")
    if change == "invented_quote":
        quote["quote"] = "Sort on y."
    elif change == "missing_support":
        quote["fields"] = ["formula"]
    elif change == "wrong_page":
        quote["pdf_page"] = 2
    raw = json.dumps(dict(evidence=[quote], observation=observation))
    if change == "duplicate_key":
        raw = raw.replace('"formula": "x"', '"formula": "y", "formula": "x"')
    prompt: dict[str, object] = {
        "user": json.dumps({"pages": [{"pdf_page": 1, "text": "Sort on x. Every month."}]})
    }
    result = parse_evidence(raw, prompt)
    assert (result is not None) == (change == "valid")
