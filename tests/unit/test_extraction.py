"""Extraction admission distinguishes uncertainty, refusal and invalid model output."""

import json

import pytest

from factorforge.domain.errors import ResearchError
from factorforge.domain.extraction import SourceExtraction, parse_extraction


def example() -> dict[str, object]:
    """An original synthetic strategy avoids leaking any pilot gold into protocol tests."""
    return {
        "status": "extracted",
        "refusal_reason": None,
        "refusal_category": None,
        "formula": "operating_income / assets",
        "required_inputs": ["assets", "operating_income"],
        "long_short_direction": "long_high_short_low",
        "bucket_count": 3,
        "weighting": "equal_weight",
        "lookback_months": None,
        "holding_months": 9,
        "rebalance_frequency": "quarterly",
        "formation_lag_months": None,
        "formation_rule": "Use the latest available annual report at quarter end.",
        "source_pages": [2, 5],
    }


def test_complete_extraction_and_unknown_are_distinct_from_zero() -> None:
    """All fields are required while an unknown quantity remains null instead of a guess."""
    parsed = parse_extraction(json.dumps(example()))
    assert parsed.holding_months == 9 and parsed.lookback_months is None
    value = example() | {"formation_lag_months": 0}
    assert parse_extraction(json.dumps(value)).formation_lag_months == 0
    value = example() | {"formula": None, "required_inputs": []}
    assert parse_extraction(json.dumps(value)).formula is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("bucket_count", True),
        ("holding_months", "9"),
        ("holding_months", 0),
        ("formation_lag_months", -1),
        ("formula", " "),
        ("required_inputs", ["assets", "assets"]),
        ("required_inputs", ["x.y"]),
        ("source_pages", []),
        ("source_pages", [2, 2]),
        ("source_pages", [True]),
        ("source_pages", [0]),
        ("weighting", "maybe"),
        ("refusal_reason", "contradictory refusal"),
        ("refusal_category", "safety"),
        ("extra", "untrusted"),
        ("formation_rule", "bad\u0000text"),
    ],
)
def test_invalid_fields_fail_closed(field: str, value: object) -> None:
    """Invalid structure never becomes a partially accepted extraction."""
    with pytest.raises(ResearchError) as failure:
        parse_extraction(json.dumps(example() | {field: value}))
    assert failure.value.code == "EXTRACTION_INVALID"


@pytest.mark.parametrize("field", list(example()))
def test_every_field_is_required(field: str) -> None:
    """Omitted fields are invalid even when their declared value can be null."""
    value = example()
    del value[field]
    with pytest.raises(ResearchError):
        parse_extraction(json.dumps(value))


def test_refusal_has_typed_reason_and_no_strategy() -> None:
    """A refusal is a distinct terminal outcome with no executable or asserted strategy."""
    value: dict[str, object] = {key: None for key in example()}
    value.update(
        status="refused",
        refusal_reason="The passage does not describe a strategy.",
        refusal_category="insufficient_information",
        required_inputs=[],
        source_pages=[],
    )
    assert parse_extraction(json.dumps(value)).status == "refused"
    value["holding_months"] = 9
    with pytest.raises(ResearchError):
        parse_extraction(json.dumps(value))


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "null",
        "```json\n{}\n```",
        "{} trailing",
        '{"status":"refused","status":"extracted"}',
        '{"ignored":NaN}',
        '{"ignored":1e999}',
        "[" * 40 + "0" + "]" * 40,
        "x" * 32769,
    ],
    ids=["array", "null", "fence", "trailing", "duplicate", "nan", "overflow", "deep", "large"],
)
def test_untrusted_output_is_bounded_unambiguous_json(raw: str) -> None:
    """No fence stripping, substring salvage, duplicate normalization or nonfinite JSON repair."""
    with pytest.raises(ResearchError) as failure:
        parse_extraction(raw)
    assert str(failure.value) == "Model extraction is invalid or exceeds limits."


def test_schema_forbids_unknown_fields_and_requires_nullable_fields() -> None:
    """Provider schema declares every field; application invariants are validated again locally."""
    schema = SourceExtraction.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(example())
