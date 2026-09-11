"""Exact conditional holdings/price inputs exclude unimplemented execution and action semantics."""

import re
from datetime import datetime
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from itertools import pairwise
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, Field, model_validator

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.factors import Contract, Digest, Identifier

PROFILE = "lean-price-only-seeded-holdings-v1"
MAX_DOTNET_COEFFICIENT = 2**96 - 1


def arithmetic_context() -> Context:
    """Fixed 128-digit arithmetic checks exact products before .NET compatibility admission."""
    return Context(
        prec=128,
        rounding=ROUND_HALF_EVEN,
        Emin=-9999,
        Emax=9999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


def dotnet_exact(text: str | Decimal) -> Decimal:
    """Require exact 96-bit coefficient and scale0..28 without context-based normalization."""
    if isinstance(text, str) and len(text) > 128:
        raise ValueError("Decimal text exceeds bound")
    try:
        value = Decimal(text)
    except DecimalException:
        raise ValueError("Decimal notation exceeds parser bounds") from None
    if not value.is_finite():
        raise ValueError("Decimal must be finite")
    parts = value.as_tuple()
    digits = list(parts.digits)
    if len(digits) > 128 or not isinstance(parts.exponent, int):
        raise ValueError("Decimal coefficient exceeds bound")
    exponent = parts.exponent
    if value == 0:
        if not -28 <= exponent <= 28:
            raise ValueError("Zero notation exceeds .NET representation")
        return value
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    if not -28 <= exponent <= 28:
        raise ValueError("Decimal exponent exceeds .NET representation")
    coefficient = int("".join(str(digit) for digit in digits))
    if coefficient * 10 ** max(exponent, 0) > MAX_DOTNET_COEFFICIENT:
        raise ValueError("Decimal coefficient exceeds .NET representation")
    return value


def decimal_text(text: str) -> str:
    """Source amounts remain exact strings with bounded significant digits and exponent."""
    if (
        type(text) is not str
        or len(text) > 64
        or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", text) is None
    ):
        raise ValueError("Amount requires bounded decimal text")
    value = dotnet_exact(text)
    parts = value.as_tuple()
    significant = len("".join(str(digit) for digit in parts.digits).rstrip("0")) or 1
    if significant > 18 or not isinstance(parts.exponent, int) or not -8 <= parts.exponent <= 12:
        raise ValueError("Source decimal exceeds profile precision")
    return text


def observed_decimal(text: str) -> str:
    """Engine/reference strings retain exact .NET values, including computed NAV precision."""
    if (
        type(text) is not str
        or len(text) > 128
        or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", text) is None
    ):
        raise ValueError("Observation requires bounded decimal text")
    dotnet_exact(text)
    return text


def utc_text(text: str) -> str:
    """Explicit UTC instants preserve the source clock without inferring a bar timezone."""
    if (
        re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z", text
        )
        is None
    ):
        raise ValueError("Snapshot time must be explicit UTC")
    value = datetime.fromisoformat(text)
    return value.isoformat().replace("+00:00", "Z")


SourceDecimal = Annotated[str, Field(max_length=64), AfterValidator(decimal_text)]
ObservedDecimal = Annotated[str, Field(max_length=128), AfterValidator(observed_decimal)]
UtcText = Annotated[str, Field(max_length=32), AfterValidator(utc_text)]


class SeededHolding(Contract):
    """Initial long holdings are conditional inventory, not claimed trades or buying power."""

    security_id: Identifier
    quantity: SourceDecimal
    average_price_usd: SourceDecimal

    @model_validator(mode="after")
    def long_only(self) -> Self:
        """The first translator cannot silently assign short funding or cost-basis semantics."""
        if Decimal(self.quantity) < 0 or Decimal(self.average_price_usd) <= 0:
            raise ValueError("Holdings require nonnegative shares and positive average price")
        with localcontext(arithmetic_context()):
            dotnet_exact(Decimal(self.quantity) * Decimal(self.average_price_usd))
        return self


class RawPrice(Contract):
    """An explicitly supplied raw USD price is a valuation input, not a synthetic executed fill."""

    security_id: Identifier
    price_usd: SourceDecimal

    @model_validator(mode="after")
    def positive_price(self) -> Self:
        """Nonpositive prices are outside this original price-only prefix."""
        if Decimal(self.price_usd) <= 0:
            raise ValueError("Price must be positive")
        return self


class PriceSnapshot(Contract):
    """Each requested UTC instant has an explicit bounded price inventory."""

    at: UtcText
    prices: Annotated[tuple[RawPrice, ...], Field(min_length=1, max_length=8)]


class PriceOnlySource(Contract):
    """Complete seeded long holdings and raw prices omit all unsupported engine semantics."""

    schema_version: Literal["lean-price-only-seeded-holdings-v1"]
    currency: Literal["USD"]
    adjustment: Literal["unadjusted"]
    cash_usd: SourceDecimal
    orders: Literal["none"]
    corporate_actions: Literal["none"]
    fees: Literal["zero"]
    cash_return: Literal["zero"]
    holdings: Annotated[tuple[SeededHolding, ...], Field(min_length=1, max_length=8)]
    snapshots: Annotated[tuple[PriceSnapshot, ...], Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def complete_inventory(self) -> Self:
        """Every price/product/cumulative NAV must fit .NET exactly before independent execution."""
        holdings = {item.security_id: item for item in self.holdings}
        if len(holdings) != len(self.holdings) or Decimal(self.cash_usd) < 0:
            raise ValueError("Unique long holdings and nonnegative cash are required")
        previous: datetime | None = None
        with localcontext(arithmetic_context()):
            for index, snapshot in enumerate(self.snapshots):
                instant = datetime.fromisoformat(snapshot.at)
                if previous is not None and instant <= previous:
                    raise ValueError("Snapshot UTC instants must strictly increase")
                previous = instant
                prices = {item.security_id: item for item in snapshot.prices}
                if len(prices) != len(snapshot.prices) or set(prices) != set(holdings):
                    raise ValueError("Snapshot price inventory must exactly match holdings")
                nav = Decimal(self.cash_usd)
                for key, holding in holdings.items():
                    product = Decimal(holding.quantity) * Decimal(prices[key].price_usd)
                    dotnet_exact(product)
                    nav += product
                    dotnet_exact(nav)
                if index == 0 and nav <= 0:
                    raise ValueError("Initial NAV must be positive")
        return self


class NavPoint(Contract):
    """A comparison observation retains its exact UTC instant and decimal NAV."""

    at: UtcText
    nav_usd: ObservedDecimal


class NavReference(Contract):
    """Expected NAV belongs only to comparison and is never an engine translator input."""

    schema_version: Literal["lean-nav-reference-v1"]
    source_sha256: Digest
    points: Annotated[tuple[NavPoint, ...], Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def ordered_points(self) -> Self:
        """No duplicate or reversed reference instant can disappear during map comparison."""
        times = [datetime.fromisoformat(point.at) for point in self.points]
        if any(right <= left for left, right in pairwise(times)):
            raise ValueError("Reference instants must strictly increase")
        return self


class VerificationRequest(Contract):
    """The caller selects declared source/reference bytes, never an executable translator."""

    schema_version: Literal["lean-verification-request-v1"]
    verification_id: UUID
    run_id: UUID
    owner_issuer: Annotated[str, Field(min_length=1, max_length=2048)]
    owner_subject: Annotated[str, Field(min_length=1, max_length=256)]
    factor_spec_sha256: Digest
    profile: Identifier
    source: ArtifactRef
    reference: ArtifactRef
    comparison: Literal["exact_nav"]

    @model_validator(mode="after")
    def bounded_references(self) -> Self:
        """Bound each JSON source before any backend or storage allocation."""
        if any(
            ref.media_type != "application/json" or not 0 < ref.size_bytes <= 2**20
            for ref in (self.source, self.reference)
        ):
            raise ValueError("Verification source/reference require bounded nonempty JSON")
        return self
