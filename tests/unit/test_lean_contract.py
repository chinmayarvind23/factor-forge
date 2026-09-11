"""Original price-only hand inputs test exact LEAN boundary semantics without engine execution."""

from decimal import Decimal, DefaultContext
from typing import Any

import pytest
from pydantic import ValidationError

from factorforge.interop.lean.contract import (
    NavPoint,
    NavReference,
    PriceOnlySource,
    decimal_text,
    dotnet_exact,
    observed_decimal,
)


def source(**changes: Any) -> PriceOnlySource:
    """Three raw prices describe an unchanged long holding with no order or corporate action."""
    return PriceOnlySource.model_validate(
        {
            "schema_version": "lean-price-only-seeded-holdings-v1",
            "currency": "USD",
            "adjustment": "unadjusted",
            "cash_usd": "0",
            "orders": "none",
            "corporate_actions": "none",
            "fees": "zero",
            "cash_return": "zero",
            "holdings": ({"security_id": "SEC-A", "quantity": "10", "average_price_usd": "100"},),
            "snapshots": tuple(
                {
                    "at": f"2024-{month_day}T20:00:00Z",
                    "prices": ({"security_id": "SEC-A", "price_usd": price},),
                }
                for month_day, price in [("04-29", "100"), ("04-30", "102"), ("05-01", "104")]
            ),
        }
        | changes
    )


def test_price_only_source_retains_exact_raw_values_and_roundtrips() -> None:
    """Validated source contains no expected NAV supplied to the future engine."""
    value = source()
    assert [row.prices[0].price_usd for row in value.snapshots] == ["100", "102", "104"]
    assert PriceOnlySource.model_validate_json(value.model_dump_json()) == value
    assert "expected" not in value.model_dump_json()


@pytest.mark.parametrize(
    "text",
    ["NaN", "Infinity", "-Infinity", "1e-9", "1e13", "1234567890123456789", " 1", "+1", "1_000"],
)
def test_input_decimal_text_is_bounded_and_exact(text: str) -> None:
    """Unsupported precision/notation cannot be coerced before the .NET boundary check."""
    with pytest.raises(ValueError):
        decimal_text(text)


@pytest.mark.parametrize("value", [1, 1.0, True])
def test_source_json_requires_decimal_strings(value: object) -> None:
    """Numeric JSON tokens cannot lose precision before strict nested validation."""
    with pytest.raises(ValidationError):
        source(cash_usd=value)


@pytest.mark.parametrize(
    "changes",
    [
        {"cash_usd": "-1"},
        {"orders": "market"},
        {"fees": "unknown"},
        {"corporate_actions": "apply"},
        {"adjustment": "total_return"},
        {"currency": "EUR"},
        {"cash_return": "interest"},
        {"algorithm": "return 1000"},
    ],
)
def test_unsupported_economics_do_not_enter_the_prefix(changes: dict[str, object]) -> None:
    """The first prefix cannot silently assume execution, adjustment or settlement equivalence."""
    with pytest.raises(ValidationError):
        source(**changes)


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate_security",
        "missing_price",
        "duplicate_price",
        "foreign_price",
        "duplicate_time",
        "backward_time",
        "naive_time",
        "short",
        "zero_price",
        "zero_nav",
    ],
)
def test_source_inventory_and_time_are_complete(kind: str) -> None:
    """Every explicit valuation instant has exactly the same stable held-ID inventory."""
    value = source().model_dump()
    if kind == "duplicate_security":
        value["holdings"] *= 2
    elif kind == "short":
        value["holdings"][0]["quantity"] = "-10"
    elif kind == "zero_nav":
        value["holdings"][0]["quantity"] = "0"
    elif kind == "duplicate_time":
        value["snapshots"] += (value["snapshots"][-1],)
    elif kind == "backward_time":
        value["snapshots"] = tuple(reversed(value["snapshots"]))
    elif kind == "naive_time":
        value["snapshots"][0]["at"] = "2024-04-29T20:00:00"
    elif kind == "missing_price":
        value["snapshots"][0]["prices"] = ()
    elif kind == "duplicate_price":
        value["snapshots"][0]["prices"] *= 2
    elif kind == "foreign_price":
        value["snapshots"][0]["prices"][0]["security_id"] = "OTHER"
    else:
        value["snapshots"][0]["prices"][0]["price_usd"] = "0"
    with pytest.raises(ValidationError):
        PriceOnlySource.model_validate(value)


def test_scalar_product_must_fit_dotnet_decimal_exactly() -> None:
    """Individually supported 18-digit values can multiply beyond the .NET coefficient budget."""
    value = source().model_dump()
    value["holdings"][0]["quantity"] = "123456789012345678"
    value["snapshots"][0]["prices"][0]["price_usd"] = "123456789012345678"
    with pytest.raises(ValidationError):
        PriceOnlySource.model_validate(value)


def test_dotnet_representation_strips_trailing_zeros_without_rounding() -> None:
    """Exactness uses the 96-bit integer and scale, not a decimal context rounding operation."""
    dotnet_exact("79228162514264337593543950335")
    dotnet_exact("0.0000000000000000000000000001")
    for value in ["79228162514264337593543950336", "1e-29"]:
        with pytest.raises(ValueError):
            dotnet_exact(value)


def test_model_copy_and_mutable_default_decimal_context_cannot_change_admission() -> None:
    """Identity boundaries revalidate nested records and arithmetic fixes every context field."""
    value = source()
    with pytest.raises(ValidationError):
        value.model_copy(update={"cash_usd": "-1"}).canonical_bytes()
    original = DefaultContext.prec
    try:
        DefaultContext.prec = 2
        assert source() == value
    finally:
        DefaultContext.prec = original


def test_zero_cannot_hide_an_unrepresentable_wire_exponent() -> None:
    """A numerically zero value still needs notation the .NET parser can represent."""
    with pytest.raises(ValueError):
        observed_decimal("0e99999999")


def test_initial_cost_basis_product_also_requires_dotnet_exactness() -> None:
    """LEAN can multiply quantity by average cost before it sees any snapshot price."""
    value = source().model_dump()
    value["holdings"][0]["quantity"] = "123456789012345678"
    value["holdings"][0]["average_price_usd"] = "123456789012345678"
    with pytest.raises(ValidationError):
        PriceOnlySource.model_validate(value)


@pytest.mark.parametrize("value", ["9" * 129, "1e999999999999999999999", "NaN", Decimal("9" * 129)])
def test_dotnet_parser_rejects_unbounded_or_nonfinite_representation(value: str | Decimal) -> None:
    """Raw helper calls fail with ValueError even for hostile exponents or Decimal objects."""
    with pytest.raises(ValueError):
        dotnet_exact(value)


@pytest.mark.parametrize("value", ["NaN", "1_000", " 1", "9" * 129])
def test_observed_decimal_requires_exact_bounded_wire_notation(value: str) -> None:
    """Returned engine values cannot use implementation-specific numeric extensions."""
    with pytest.raises(ValueError):
        observed_decimal(value)


def test_reference_inventory_rejects_duplicate_instants() -> None:
    """Expected rows cannot overwrite one another when materialized as a comparison map."""
    point = NavPoint(at=source().snapshots[0].at, nav_usd="1000")
    with pytest.raises(ValidationError):
        NavReference(
            schema_version="lean-nav-reference-v1", source_sha256="a" * 64, points=(point, point)
        )


@pytest.mark.parametrize("kind", ["holdings", "snapshots"])
def test_declared_source_work_inventory_is_bounded(kind: str) -> None:
    """Repeated source collections cannot exceed eight securities or 128 valuation instants."""
    value = source().model_dump()
    value[kind] *= 129
    with pytest.raises(ValidationError):
        PriceOnlySource.model_validate(value)
