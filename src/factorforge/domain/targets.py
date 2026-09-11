"""Exact conditional targets do not imply source selection, funding or order execution."""

import math
import re
from decimal import Decimal, DecimalException
from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.calendar import FormationPlan
from factorforge.domain.factors import (
    AllocationSpec,
    Contract,
    CostSpec,
    Digest,
    Identifier,
    PortfolioSpec,
)


def bounded_fraction(value: Fraction) -> Fraction:
    """Bound intermediate denominators before repeated rational addition can grow without limit."""
    if value.numerator.bit_length() > 2048 or value.denominator.bit_length() > 2048:
        raise ValueError("Rational arithmetic exceeds supported precision")
    return value


class Rational(Contract):
    """Reduced integer strings preserve exact weights without a hidden residual-rounding rule."""

    numerator: Annotated[str, Field(max_length=513, pattern=r"^(?:0|-?[1-9][0-9]{0,511})$")]
    denominator: Annotated[str, Field(max_length=512, pattern=r"^[1-9][0-9]{0,511}$")]

    @model_validator(mode="after")
    def reduced(self) -> Self:
        """Canonical components prevent alternate encodings of an identical rational weight."""
        if math.gcd(int(self.numerator), int(self.denominator)) != 1:
            raise ValueError("Rational components must be reduced")
        return self

    @classmethod
    def from_fraction(cls, value: Fraction) -> "Rational":
        """Serialization follows Python's exact reduced representation after a resource bound."""
        bounded_fraction(value)
        return cls(numerator=str(value.numerator), denominator=str(value.denominator))

    def as_fraction(self) -> Fraction:
        """Copied models cannot bypass canonical component validation at an arithmetic boundary."""
        value = Rational.model_validate(self)
        return Fraction(int(value.numerator), int(value.denominator))


class SignalValue(Contract):
    """A caller-selected scalar keeps its Decimal spelling until exact rank assignment."""

    security_id: Identifier
    signal: Annotated[str, Field(max_length=128)] | None
    capitalization: Annotated[str, Field(max_length=128)] | None

    @field_validator("signal", "capitalization")
    @classmethod
    def finite_number(cls, value: str | None) -> str | None:
        """Missing values remain null; invalid or unbounded numbers cannot become exclusions."""
        if value is None:
            return value
        if (
            re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value)
            is None
        ):
            raise ValueError("Signal inputs require decimal numbers")
        try:
            number = Decimal(value)
            if (
                not number.is_finite()
                or number.copy_abs() > Decimal("1e100")
                or (number and number.adjusted() < -100)
            ):
                raise ValueError("Signal input exceeds the numeric bounds")
        except DecimalException:
            raise ValueError("Signal input is invalid") from None
        return value

    @model_validator(mode="after")
    def positive_capitalization(self) -> Self:
        """Nonpositive capitalization is corrupt data even for equal-weight candidates."""
        if self.capitalization is not None and Decimal(self.capitalization) <= 0:
            raise ValueError("Capitalization must be strictly positive")
        return self


class CrossSection(Contract):
    """Preselected rows retain references; selection and byte verification are upstream."""

    source_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1, max_length=32)]
    formation: FormationPlan
    universe: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=10000)]
    observations: Annotated[tuple[SignalValue, ...], Field(max_length=10000)]

    @model_validator(mode="after")
    def unique_inventory(self) -> Self:
        """One selected scalar per ID avoids resolving competing revisions in the target layer."""
        if len(set(self.universe)) != len(self.universe) or len(
            {row.security_id for row in self.observations}
        ) != len(self.observations):
            raise ValueError("Cross-section identities must be unique")
        return self


class PositionWeight(Contract):
    """A conditional weight is expressed relative to the caller's shared pre-trade NAV basis."""

    security_id: Identifier
    weight: Rational


class BucketPosition(PositionWeight):
    """All eligible rows retain their bucket, including zero-weight interior securities."""

    bucket: Annotated[int, Field(ge=0, le=99)]


def _validate_partition(
    rule: AllocationSpec,
    positions: tuple[BucketPosition, ...],
    excluded: tuple[str, ...],
) -> None:
    """Shared inventory arithmetic binds unit sleeves without asserting any funding convention."""
    ids = {row.security_id for row in positions}
    if (
        len(ids) != len(positions)
        or len(set(excluded)) != len(excluded)
        or ids & set(excluded)
        or len(positions) + len(excluded) > 10000
        or excluded != tuple(sorted(excluded))
    ):
        raise ValueError("Target and exclusion identities must be distinct and unique")
    q, r = divmod(len(positions), rule.bucket_count)
    if q < rule.minimum_bucket_size:
        raise ValueError("Every bucket must meet its minimum")
    expected = tuple(bucket for bucket in range(rule.bucket_count) for _ in range(q + (bucket < r)))
    if tuple(row.bucket for row in positions) != expected:
        raise ValueError("Target bucket inventory does not match the partition policy")
    low_sign = -1 if rule.direction == "long_high_short_low" else 1
    totals = [Fraction(0) for _ in range(rule.bucket_count)]
    for row in positions:
        weight = row.weight.as_fraction()
        sign = (
            low_sign if row.bucket == 0 else -low_sign if row.bucket == rule.bucket_count - 1 else 0
        )
        if (sign == 0 and weight != 0) or (sign != 0 and not 0 < sign * weight <= 1):
            raise ValueError("Position sign is inconsistent with its bucket")
        if rule.weighting == "equal_weight" and weight != Fraction(sign, q + (row.bucket < r)):
            raise ValueError("Equal weights must agree within each bucket")
        totals[row.bucket] = bounded_fraction(totals[row.bucket] + weight)
    if totals[0] != low_sign or totals[-1] != -low_sign:
        raise ValueError("Extreme sleeves must normalize exactly to unit exposure")


class AllocationTemplate(Contract):
    """A preselected unit-sleeve template requires later source, funding and execution admission."""

    schema_version: Literal["allocation-template-v1"] = "allocation-template-v1"
    scope: Literal["unit-sleeve-template"] = "unit-sleeve-template"
    input_sha256: Digest
    allocation_sha256: Digest
    allocation: AllocationSpec
    formation: FormationPlan
    positions: Annotated[tuple[BucketPosition, ...], Field(min_length=2, max_length=10000)]
    excluded: Annotated[tuple[Identifier, ...], Field(max_length=10000)]

    @model_validator(mode="after")
    def coherent_allocation(self) -> Self:
        """Copied and loaded templates must retain their exact policy and normalized partition."""
        if self.allocation_sha256 != self.allocation.sha256:
            raise ValueError("Allocation policy identity does not match")
        _validate_partition(self.allocation, self.positions, self.excluded)
        return self


class TargetPlan(Contract):
    """Target inventories enforce partition and sleeve arithmetic, not execution permission."""

    schema_version: Literal["conditional-targets-v1"] = "conditional-targets-v1"
    scope: Literal["conditional-preselected-signal-targets"] = (
        "conditional-preselected-signal-targets"
    )
    input_sha256: Digest
    portfolio_sha256: Digest
    portfolio: PortfolioSpec
    formation: FormationPlan
    positions: Annotated[tuple[BucketPosition, ...], Field(min_length=2, max_length=10000)]
    excluded: Annotated[tuple[Identifier, ...], Field(max_length=10000)]

    @model_validator(mode="after")
    def coherent_targets(self) -> Self:
        """Reloaded targets retain bucket counts, unique IDs and normalized sleeve totals."""
        rule = self.portfolio
        if self.portfolio_sha256 != rule.sha256:
            raise ValueError("Target policy identity does not match")
        _validate_partition(rule, self.positions, self.excluded)
        return self


class TradeCost(Contract):
    """Trade-only estimates exclude ongoing carry, which requires elapsed exposures and funding."""

    scope: Literal["conditional-trade-only-pre-trade-nav"] = "conditional-trade-only-pre-trade-nav"
    costs: CostSpec
    turnover: Rational
    commission: Rational
    slippage: Rational

    @model_validator(mode="after")
    def coherent_costs(self) -> Self:
        """Reloaded cost totals must agree with nonnegative turnover and declared basis points."""
        turnover = self.turnover.as_fraction()
        if (
            turnover < 0
            or self.commission.as_fraction()
            != turnover * Fraction(self.costs.commission_bps, 10000)
            or self.slippage.as_fraction() != turnover * Fraction(self.costs.slippage_bps, 10000)
        ):
            raise ValueError("Trade cost arithmetic is inconsistent")
        return self
