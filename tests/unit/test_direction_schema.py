"""The experimental grammar admits only coherent judgments and mirrors its Pydantic types."""

import json

import pytest
from pydantic import ValidationError

from factorforge.retrieval.direction_review import DirectionObservation
from factorforge.retrieval.direction_schema import DirectionEnvelope, direction_envelope_schema


@pytest.mark.parametrize(
    "direction,quote,page,uncertainty,valid",
    [
        ("long_high_short_low", "Buy high, short low", 1, None, True),
        ("long_low_short_high", "Buy low, short high", 1, None, True),
        (None, None, None, "Missing legs", True),
        (None, "Unspecified", 1, "Missing legs", False),
        ("long_high_short_low", "Buy high", 1, "Missing short leg", False),
        (None, None, None, None, False),
        ("other", "Text", 1, None, False),
        ("long_high_short_low", "", 1, None, False),
        ("long_high_short_low", "Text", 0, None, False),
        (None, None, None, "", False),
    ],
)
def test_coherent_wire_states(
    direction: str | None,
    quote: str | None,
    page: int | None,
    uncertainty: str | None,
    valid: bool,
) -> None:
    """Invalid combinations remain rejected rather than repaired or relabeled as uncertainty."""
    wire = {
        "judgment": dict(direction=direction, quote=quote, pdf_page=page, uncertainty=uncertainty)
    }
    if not valid:
        with pytest.raises(ValidationError):
            DirectionEnvelope.model_validate(wire)
        return
    parsed = DirectionEnvelope.model_validate(wire)
    assert DirectionEnvelope.model_validate_json(parsed.canonical_bytes()) == parsed
    assert DirectionObservation.model_validate(parsed.judgment.model_dump()).direction == direction


def test_schema_inlining_preserves_closed_pydantic_branches() -> None:
    """Inlining changes only references; required properties and disjoint states stay identical."""
    original = DirectionEnvelope.model_json_schema()
    schema = direction_envelope_schema()
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["judgment"]
    branches = schema["properties"]["judgment"]["anyOf"]
    assert branches == [
        original["$defs"][name] for name in ("SupportedDirection", "UncertainDirection")
    ]
    for branch in branches:
        assert branch["additionalProperties"] is False
        assert set(branch["required"]) == {"direction", "quote", "pdf_page", "uncertainty"}
