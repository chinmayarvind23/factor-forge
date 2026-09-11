"""Bounded exact post-fee notionals and collateral evidence do not admit trades or quotes."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise
from math import gcd
from typing import Annotated, Literal, Self

from pydantic import Field, ValidationInfo, field_validator, model_validator

from factorforge.domain.accounting import LedgerCosts
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Digest, Identifier
from factorforge.domain.targets import PositionWeight, Rational

MAX_SECURITIES = 8
MAX_BITS = 2048
MAX_AMOUNT = Fraction(10**24)


class _Failure(ValueError):
    """Internal validation preserves a safe code for public ResearchError translation."""

    def __init__(self, code: str) -> None:
        """Never retain an input value or host diagnostic in numeric failures."""
        super().__init__(code)
        self.code = code


def _error(code: str) -> ResearchError:
    """Pure calculation failures expose only a fixed bounded application diagnostic."""
    return ResearchError(
        code, "Funding calculation exceeds supported exact precision or policy.", 422
    )


def _bounded(value: Fraction) -> Fraction:
    """Validate exact type and both integer sizes before arithmetic or decimal conversion."""
    if type(value) is not Fraction:
        raise _Failure("FUNDING_INPUT_INVALID")
    if not hasattr(value, "numerator") or not hasattr(value, "denominator"):
        raise _Failure("FUNDING_INPUT_INVALID")
    if (
        type(value.numerator) is not int
        or type(value.denominator) is not int
        or value.denominator <= 0
    ):
        raise _Failure("FUNDING_INPUT_INVALID")
    if value.numerator.bit_length() > MAX_BITS or value.denominator.bit_length() > MAX_BITS:
        raise _Failure("FUNDING_NUMERIC_BOUND")
    if gcd(value.numerator, value.denominator) != 1:
        raise _Failure("FUNDING_INPUT_INVALID")
    return value


def _add(left: Fraction, right: Fraction) -> Fraction:
    """Each checked addition has at most 4097-bit cross-products before reduction."""
    return _bounded(_bounded(left) + _bounded(right))


def _multiply(left: Fraction, right: Fraction) -> Fraction:
    """Checked 2048-bit operands bound unreduced multiplication before it occurs."""
    return _bounded(_bounded(left) * _bounded(right))


def _divide(left: Fraction, right: Fraction) -> Fraction:
    """Bound reciprocal arithmetic and reject a zero divisor before Fraction allocation."""
    _bounded(left)
    _bounded(right)
    if right == 0:
        raise _Failure("FUNDING_INPUT_INVALID")
    return _bounded(left / right)


def _sum(values: Iterable[Fraction]) -> Fraction:
    """Internal bounded inventories accumulate only through checked rational addition."""
    total = Fraction(0)
    for value in values:
        total = _add(total, value)
    return total


def _amount(value: Fraction) -> Fraction:
    """Signed money and quantities remain within the existing ledger's 1e24 magnitude."""
    _bounded(value)
    if abs(value) > MAX_AMOUNT:
        raise _Failure("FUNDING_NUMERIC_BOUND")
    return value


def _wire(value: Fraction) -> Rational:
    """Serialized components must fit the existing 512-digit rational wire representation."""
    _bounded(value)
    numerator, denominator = str(value.numerator), str(value.denominator)
    if len(numerator.lstrip("-")) > 512 or len(denominator) > 512:
        raise _Failure("FUNDING_NUMERIC_BOUND")
    return Rational(numerator=numerator, denominator=denominator)


def _inventory(value: object, *, json_wire: bool = False) -> object:
    """Reject oversized or mutable inventories before Pydantic visits nested records."""
    if json_wire and type(value) is list and len(value) <= MAX_SECURITIES:
        value = tuple(value)
    if type(value) is not tuple or len(value) > MAX_SECURITIES:
        raise ValueError("Funding requires a bounded tuple inventory")
    return value


class SignedNotional(Contract):
    """A signed marked value names its security but does not authenticate its price source."""

    security_id: Identifier
    notional_usd: Rational

    @model_validator(mode="after")
    def bounded_value(self) -> Self:
        """Validate nested copies and magnitude before any aggregate calculation."""
        _amount(self.notional_usd.as_fraction())
        return self


class FundingRequest(Contract):
    """A fixed unit-long/unit-short or liquidation request binds every sizing choice."""

    schema_version: Literal["post-fee-funding-request-v1"] = "post-fee-funding-request-v1"
    pre_trade_nav_usd: Rational
    old_notionals: Annotated[tuple[SignedNotional, ...], Field(max_length=8)]
    target_weights: Annotated[tuple[PositionWeight, ...], Field(max_length=8)]
    costs: LedgerCosts
    purpose: Literal["rebalance", "liquidate"]

    @field_validator("old_notionals", "target_weights", mode="before")
    @classmethod
    def bounded_inventory(cls, value: object, info: ValidationInfo) -> object:
        """Inventory caps precede recursive validation even for forged copied requests."""
        return _inventory(value, json_wire=info.mode == "json")

    @field_validator("old_notionals", "target_weights")
    @classmethod
    def ordered_inventory[Row: SignedNotional | PositionWeight](
        cls, value: tuple[Row, ...]
    ) -> tuple[Row, ...]:
        """Order has no economic meaning; duplicate IDs never collapse silently."""
        if len({row.security_id for row in value}) != len(value):
            raise ValueError("Funding inventory identities must be unique")
        return tuple(sorted(value, key=lambda row: row.security_id))

    @model_validator(mode="after")
    def complete_request(self) -> Self:
        """Only exact unit sleeves or explicit all-zero liquidation are supported."""
        if _amount(self.pre_trade_nav_usd.as_fraction()) <= 0:
            raise ValueError("Pre-trade NAV must be positive")
        if (
            len(
                {row.security_id for row in self.old_notionals}
                | {row.security_id for row in self.target_weights}
            )
            > MAX_SECURITIES
        ):
            raise ValueError("Funding union inventory exceeds bound")
        weights = tuple(_bounded(row.weight.as_fraction()) for row in self.target_weights)
        if self.purpose == "liquidate":
            if any(weights):
                raise ValueError("Liquidation cannot open a replacement target")
        elif (
            _sum(value for value in weights if value > 0) != 1
            or _sum(value for value in weights if value < 0) != -1
        ):
            raise ValueError("Rebalance targets require exact unit long and short sleeves")
        return self


class FundingPosition(Contract):
    """Every held/target ID retains its old value, template and exact proposed trade."""

    security_id: Identifier
    old_notional_usd: Rational
    target_weight: Rational
    target_notional_usd: Rational
    trade_notional_usd: Rational


@dataclass(frozen=True)
class _Solution:
    """One bounded solver result is shared by construction and saved-output verification."""

    nav: Fraction
    positions: tuple[FundingPosition, ...]
    turnover: Fraction
    commission: Fraction
    slippage: Fraction


def _trades(
    keys: tuple[str, ...], old: dict[str, Fraction], weights: dict[str, Fraction], nav: Fraction
) -> tuple[FundingPosition, ...]:
    """Liquidate absent targets while retaining exact per-security trade identities."""
    rows = []
    for key in keys:
        previous, weight = old.get(key, Fraction(0)), weights.get(key, Fraction(0))
        target = _amount(_multiply(nav, weight))
        trade = _amount(_add(target, -previous))
        rows.append(
            FundingPosition(
                security_id=key,
                old_notional_usd=_wire(previous),
                target_weight=_wire(weight),
                target_notional_usd=_wire(target),
                trade_notional_usd=_wire(trade),
            )
        )
    return tuple(rows)


def _root(
    equity: Fraction,
    cost: Fraction,
    keys: tuple[str, ...],
    old: dict[str, Fraction],
    weights: dict[str, Fraction],
) -> Fraction:
    """Solve a monotone piecewise-affine equation at exact rational interval candidates."""
    if _multiply(cost, _sum(abs(value) for value in weights.values())) >= 1:
        raise _Failure("FUNDING_SLOPE_UNSUPPORTED")
    if _multiply(cost, _sum(abs(value) for value in old.values())) >= equity:
        raise _Failure("FUNDING_LIQUIDATION_INFEASIBLE")
    breakpoints = {Fraction(0), equity}
    for key, weight in weights.items():
        if weight:
            candidate = _divide(old.get(key, Fraction(0)), weight)
            if 0 < candidate < equity:
                breakpoints.add(candidate)
    for left, right in pairwise(sorted(breakpoints)):
        middle = _divide(_add(left, right), Fraction(2))
        a, b = Fraction(0), Fraction(0)
        for key in keys:
            weight, previous = weights.get(key, Fraction(0)), old.get(key, Fraction(0))
            sign = Fraction(1) if _add(_multiply(middle, weight), -previous) >= 0 else Fraction(-1)
            a, b = _add(a, _multiply(sign, weight)), _add(b, _multiply(sign, previous))
        candidate = _divide(_add(equity, _multiply(cost, b)), _add(Fraction(1), _multiply(cost, a)))
        if left <= candidate <= right:
            return candidate
    raise _Failure("FUNDING_SOLUTION_INVALID")


def _solution(request: FundingRequest) -> _Solution:
    """Derive root and costs, then verify the original equation rather than just its interval."""
    old = {row.security_id: row.notional_usd.as_fraction() for row in request.old_notionals}
    weights = {row.security_id: row.weight.as_fraction() for row in request.target_weights}
    keys = tuple(sorted(old.keys() | weights.keys()))
    equity = request.pre_trade_nav_usd.as_fraction()
    commission_rate = Fraction(request.costs.commission_bps, 10000)
    slippage_rate = Fraction(request.costs.slippage_bps, 10000)
    nav = _root(equity, _add(commission_rate, slippage_rate), keys, old, weights)
    positions = _trades(keys, old, weights, nav)
    turnover = _sum(abs(row.trade_notional_usd.as_fraction()) for row in positions)
    commission, slippage = _multiply(turnover, commission_rate), _multiply(turnover, slippage_rate)
    if _add(nav, _add(commission, slippage)) != equity or nav <= 0:
        raise _Failure("FUNDING_SOLUTION_INVALID")
    return _Solution(nav, positions, turnover, commission, slippage)


class FundingPlan(Contract):
    """A verified notional solution carries no quote, borrow, quantity or execution admission."""

    schema_version: Literal["post-fee-funding-plan-v1"] = "post-fee-funding-plan-v1"
    scope: Literal["pure-post-fee-notional-solution"] = "pure-post-fee-notional-solution"
    request: FundingRequest
    request_sha256: Digest
    sizing_nav_usd: Rational
    positions: Annotated[tuple[FundingPosition, ...], Field(max_length=8)]
    absolute_trade_notional_usd: Rational
    commission_usd: Rational
    slippage_usd: Rational

    @field_validator("positions", mode="before")
    @classmethod
    def bounded_inventory(cls, value: object, info: ValidationInfo) -> object:
        """Cap saved plan inventories before recursively reading per-security result values."""
        return _inventory(value, json_wire=info.mode == "json")

    @model_validator(mode="after")
    def exact_solution(self) -> Self:
        """Reloaded outputs must equal the unique solution of their complete referenced request."""
        result = _solution(self.request)
        if self.request_sha256 != self.request.sha256 or (
            self.sizing_nav_usd.as_fraction(),
            self.positions,
            self.absolute_trade_notional_usd.as_fraction(),
            self.commission_usd.as_fraction(),
            self.slippage_usd.as_fraction(),
        ) != (result.nav, result.positions, result.turnover, result.commission, result.slippage):
            raise ValueError("Funding result does not match its exact input equation")
        return self


def solve_post_fee(request: FundingRequest) -> FundingPlan:
    """Return one exact notional solution; quote/quantity/funding-path admission is separate."""
    try:
        value = FundingRequest.model_validate(request)
        result = _solution(value)
        return FundingPlan(
            request=value,
            request_sha256=value.sha256,
            sizing_nav_usd=_wire(result.nav),
            positions=result.positions,
            absolute_trade_notional_usd=_wire(result.turnover),
            commission_usd=_wire(result.commission),
            slippage_usd=_wire(result.slippage),
        )
    except _Failure as error:
        raise _error(error.code) from None
    except (ValueError, TypeError):
        raise _error("FUNDING_INPUT_INVALID") from None


def _decimal(value: Fraction, *, quantity: bool) -> Decimal:
    """Construct a terminating decimal without division, rounding or process-context dependence."""
    _amount(value)
    denominator = value.denominator
    powers = []
    for prime in (2, 5):
        count = 0
        while denominator % prime == 0:
            denominator //= prime
            count += 1
        powers.append(count)
    scale = max(powers)
    code = "FUNDING_QUANTITY_PRECISION" if quantity else "FUNDING_ACCOUNTING_PRECISION"
    if denominator != 1 or (quantity and scale > 18):
        raise _Failure(code)
    twos, fives = scale - powers[0], scale - powers[1]
    if value.numerator.bit_length() + twos + 3 * fives > MAX_BITS:
        raise _Failure(code)
    coefficient = abs(value.numerator) * 2**twos * 5**fives
    digits = str(coefficient)
    if coefficient:
        while digits.endswith("0"):
            digits = digits[:-1]
            scale -= 1
    if len(digits) > (43 if quantity else 50):
        raise _Failure(code)
    return Decimal((int(value < 0), tuple(int(digit) for digit in digits), -scale))


def exact_quantity(value: Fraction) -> Decimal:
    """Require exact terminating signed shares within the current ledger input bounds."""
    try:
        return _decimal(value, quantity=True)
    except _Failure as error:
        raise _error(error.code) from None


def exact_accounting(value: Fraction) -> Decimal:
    """Require an exact finite 50-digit ledger amount; this never authorizes a fill quantity."""
    try:
        return _decimal(value, quantity=False)
    except _Failure as error:
        raise _error(error.code) from None


class CollateralObservation(Contract):
    """Failed cash-reserve states stay representable instead of disappearing behind an exception."""

    schema_version: Literal["collateral-observation-v1"] = "collateral-observation-v1"
    policy: Literal["current_short_liability_cash_reserve_v1"] = (
        "current_short_liability_cash_reserve_v1"
    )
    cash_usd: Rational
    notionals: Annotated[tuple[SignedNotional, ...], Field(max_length=8)]
    restricted_cash_usd: Rational
    free_cash_usd: Rational
    nav_usd: Rational
    status: Literal["funded", "unfunded", "insolvent"]
    failure_code: Literal["FUNDING_COLLATERAL_DEFICIT", "FUNDING_INSOLVENT"] | None

    @field_validator("notionals", mode="before")
    @classmethod
    def bounded_inventory(cls, value: object, info: ValidationInfo) -> object:
        """Copied observations cannot trigger unbounded nested validation."""
        return _inventory(value, json_wire=info.mode == "json")

    @model_validator(mode="after")
    def exact_observation(self) -> Self:
        """Retained failure labels and cash values must match the declared marked inventory."""
        if tuple(sorted(self.notionals, key=lambda row: row.security_id)) != self.notionals or len(
            {row.security_id for row in self.notionals}
        ) != len(self.notionals):
            raise ValueError("Collateral inventory must be unique and canonical")
        cash = _amount(self.cash_usd.as_fraction())
        restricted = _sum(
            -row.notional_usd.as_fraction()
            for row in self.notionals
            if row.notional_usd.as_fraction() < 0
        )
        free = _add(cash, -restricted)
        nav = _add(cash, _sum(row.notional_usd.as_fraction() for row in self.notionals))
        status, code = _collateral_status(nav, free)
        if (
            self.restricted_cash_usd.as_fraction(),
            self.free_cash_usd.as_fraction(),
            self.nav_usd.as_fraction(),
            self.status,
            self.failure_code,
        ) != (restricted, free, nav, status, code):
            raise ValueError("Collateral observation does not match its exact marked state")
        return self


def _collateral_status(
    nav: Fraction, free: Fraction
) -> tuple[
    Literal["funded", "unfunded", "insolvent"],
    Literal["FUNDING_COLLATERAL_DEFICIT", "FUNDING_INSOLVENT"] | None,
]:
    """Insolvency takes diagnostic precedence while all observed cash values remain retained."""
    return (
        ("insolvent", "FUNDING_INSOLVENT")
        if nav <= 0
        else ("unfunded", "FUNDING_COLLATERAL_DEFICIT")
        if free < 0
        else ("funded", None)
    )


def _cash_fraction(value: Decimal) -> Fraction:
    """Inspect Decimal shape before Fraction can allocate powers from a hostile exponent."""
    if type(value) is not Decimal or not value.is_finite():
        raise _Failure("FUNDING_INPUT_INVALID")
    parts = value.as_tuple()
    if len(parts.digits) > 50 or not isinstance(parts.exponent, int) or abs(parts.exponent) > 600:
        raise _Failure("FUNDING_NUMERIC_BOUND")
    return _amount(Fraction(value))


def observe_collateral(
    *, cash_usd: Decimal, notionals: tuple[SignedNotional, ...]
) -> CollateralObservation:
    """Observe the explicit current-liability reserve; callers must stop on a failed status.

    This is not broker margin or borrowing permission. Quotes, instants and historical-price
    completeness are the caller's verified execution inputs and are absent from this pure model.
    """
    try:
        cash = _cash_fraction(cash_usd)
        _inventory(notionals)
        rows = tuple(
            sorted(
                (SignedNotional.model_validate(row) for row in notionals),
                key=lambda row: row.security_id,
            )
        )
        restricted = _sum(
            -row.notional_usd.as_fraction() for row in rows if row.notional_usd.as_fraction() < 0
        )
        free = _add(cash, -restricted)
        nav = _add(cash, _sum(row.notional_usd.as_fraction() for row in rows))
        status, code = _collateral_status(nav, free)
        return CollateralObservation(
            cash_usd=_wire(cash),
            notionals=rows,
            restricted_cash_usd=_wire(restricted),
            free_cash_usd=_wire(free),
            nav_usd=_wire(nav),
            status=status,
            failure_code=code,
        )
    except _Failure as error:
        raise _error(error.code) from None
    except (ValueError, TypeError):
        raise _error("FUNDING_INPUT_INVALID") from None
