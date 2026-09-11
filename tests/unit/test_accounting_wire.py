"""Decimal wire values must retain source precision before ledger arithmetic begins."""

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from factorforge.domain.accounting import Position, PriceMark


@pytest.mark.parametrize("number", ["1.000000000000000001", "1", "1.0"])
@pytest.mark.parametrize("kind", ["input", "saved_position"])
def test_json_numeric_amounts_are_rejected_before_float_conversion(number: str, kind: str) -> None:
    """Both fresh quotes and reloaded positions require exact decimal text on the wire."""
    model: type[PriceMark] | type[Position]
    if kind == "input":
        payload = {
            "source_id": "original",
            "security_id": "SEC-A",
            "observed_at": "2024-04-29T20:00:00Z",
            "available_at": "2024-04-29T20:00:00Z",
            "price_usd": "WIRE_AMOUNT",
            "adjustment": "unadjusted",
            "currency": "USD",
        }
        model = PriceMark
    else:
        payload = {"security_id": "SEC-A", "signed_shares": "WIRE_AMOUNT"}
        model = Position
    raw = json.dumps(payload).replace('"WIRE_AMOUNT"', number)
    with pytest.raises(ValidationError):
        model.model_validate_json(raw)


def test_decimal_text_round_trips_without_losing_small_share_differences() -> None:
    """Canonical saved text and typed Python Decimals preserve the same exact amount."""
    expected = Decimal("1.000000000000000001")
    position = Position(security_id="SEC-A", signed_shares=expected)
    assert Position.model_validate_json(position.model_dump_json()).signed_shares == expected
    with pytest.raises(ValidationError):
        Position.model_validate({"security_id": "SEC-A", "signed_shares": str(expected)})


@pytest.mark.parametrize("value", ["invalid", "9" * 129, "NaN", "Infinity"])
def test_invalid_decimal_text_is_rejected(value: str) -> None:
    """Text transport cannot bypass finite magnitude or parsing resource limits."""
    with pytest.raises(ValidationError):
        Position.model_validate_json(json.dumps({"security_id": "SEC-A", "signed_shares": value}))


def test_amount_schema_advertises_the_required_decimal_text() -> None:
    """Generated clients should send the same string representation as saved records."""
    assert Position.model_json_schema()["properties"]["signed_shares"]["type"] == "string"
