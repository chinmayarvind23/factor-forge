"""Strict conditional ledger records distinguish authored fills from admitted strategies."""

from datetime import UTC, datetime
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
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


def exact_decimal_wire(value: object, info: ValidationInfo) -> object:
    """JSON decimal strings avoid binary-float rounding before ledger precision checks."""
    if info.mode == "json":
        if not isinstance(value, str) or len(value) > 128:
            raise ValueError("Accounting amounts require bounded decimal strings in JSON")
        try:
            return Decimal(value)
        except DecimalException:
            raise ValueError("Accounting amount is invalid decimal text") from None
    return value


Identity = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
Amount = Annotated[
    Decimal,
    Field(ge=Decimal("-1e24"), le=Decimal("1e24"), allow_inf_nan=False),
    BeforeValidator(exact_decimal_wire, json_schema_input_type=str),
]
Positive = Annotated[Amount, Field(gt=0)]
Nonnegative = Annotated[Amount, Field(ge=0)]


def accounting_context() -> Context:
    """Every arithmetic context field is explicit and independent of mutable process defaults."""
    return Context(
        prec=50,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


def accounting_utc(value: datetime) -> datetime:
    """Validate and normalize a representable aware instant before ordering any ledger events."""
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Accounting timestamps must be aware")
    try:
        return value.astimezone(UTC)
    except OverflowError:
        raise ValueError("Accounting timestamp cannot be represented in UTC") from None


class LedgerRecord(BaseModel):
    """Nested values are immutable and revalidated at each public arithmetic boundary."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always"
    )

    @field_validator("*", mode="after")
    @classmethod
    def normalized_time(cls, value: object) -> object:
        """Canonical UTC timestamps keep comparison and saved replay independent of offsets."""
        return accounting_utc(value) if isinstance(value, datetime) else value


class LedgerInput(LedgerRecord):
    """Input decimal precision is bounded before arithmetic or integer conversion."""

    @field_validator("*", mode="after")
    @classmethod
    def bounded_precision(cls, value: object) -> object:
        """Tiny exponents and arbitrary coefficient lengths cannot consume unbounded work."""
        if isinstance(value, Decimal):
            parts = value.as_tuple()
            if (
                len(parts.digits) > 43
                or not isinstance(parts.exponent, int)
                or parts.exponent < -18
            ):
                raise ValueError("Input decimals exceed supported precision")
        return value


class PriceMark(LedgerInput):
    """An exact contemporaneous raw quote cannot double count an adjusted return series."""

    source_id: Identity
    security_id: Identity
    observed_at: AwareDatetime
    available_at: AwareDatetime
    price_usd: Positive
    adjustment: Literal["unadjusted"]
    currency: Literal["USD"]


class ConditionalFill(LedgerInput):
    """The caller supplies an authored fill; this record makes no execution-feasibility claim."""

    fill_id: Identity
    security_id: Identity
    signed_quantity: Amount
    executed_at: AwareDatetime
    quote: PriceMark

    @model_validator(mode="after")
    def exact_quote(self) -> Self:
        """No mismatched identity, stale quote or unavailable price may fund a fill."""
        if (
            self.signed_quantity == 0
            or self.security_id != self.quote.security_id
            or self.executed_at != self.quote.observed_at
            or self.quote.available_at > self.executed_at
        ):
            raise ValueError("Conditional fill requires a matching exact-time available raw quote")
        return self


class CorporateAction(LedgerInput):
    """Availability is information; economic effect and later settlement are separate clocks."""

    event_id: Identity
    security_id: Identity
    kind: Literal["split", "cash_dividend", "terminal_exit"]
    available_at: AwareDatetime
    effective_at: AwareDatetime
    pay_at: AwareDatetime | None
    old_shares: Positive | None
    new_shares: Positive | None
    cash_per_share: Nonnegative | None

    @model_validator(mode="after")
    def coherent_terms(self) -> Self:
        """Only supported terms exist, and settlement cannot precede entitlement."""
        if self.kind == "split":
            if (
                self.old_shares is None
                or self.new_shares is None
                or self.pay_at is not None
                or self.cash_per_share is not None
            ):
                raise ValueError("A split requires only its positive old/new share ratio")
        else:
            if self.old_shares is not None or self.new_shares is not None:
                raise ValueError("Cash events cannot carry a split ratio")
            if self.kind == "cash_dividend" and self.cash_per_share is None:
                raise ValueError("A dividend requires known per-share cash terms")
            if (self.cash_per_share is None) != (self.pay_at is None):
                raise ValueError("Known cash terms require an explicit payment instant")
        if self.pay_at is not None and self.pay_at < self.effective_at:
            raise ValueError("Payment cannot precede economic entitlement")
        return self


class LedgerCosts(LedgerRecord):
    """The first explicit cost profile supports trade fees and rejects unsupported carry."""

    commission_bps: Annotated[int, Field(ge=0, le=10000)]
    slippage_bps: Annotated[int, Field(ge=0, le=10000)]
    annual_borrow_bps: Literal[0]
    annual_financing_bps: Literal[0]
    annual_interest_bps: Literal[0]

    @field_validator(
        "annual_borrow_bps", "annual_financing_bps", "annual_interest_bps", mode="before"
    )
    @classmethod
    def exact_zero(cls, value: object) -> object:
        """Boolean and floating zero are not explicit integer cost declarations."""
        if type(value) is not int:
            raise ValueError("Carry costs require explicit integer zero")
        return value


class Position(LedgerRecord):
    """Signed shares remain associated with a permanent security identity after an exit."""

    security_id: Identity
    signed_shares: Amount


class CashClaim(LedgerRecord):
    """A fixed signed entitlement survives a later position disposal until its own pay time."""

    event_id: Identity
    security_id: Identity
    kind: Literal["cash_dividend", "terminal_exit"]
    signed_amount_usd: Amount
    pay_at: AwareDatetime


class AppliedPhase(LedgerRecord):
    """One phase identity is recorded once even when an identical event is replayed."""

    event_id: Identity
    phase: Literal["effective", "payment", "fill"]
    occurred_at: AwareDatetime


class LedgerState(LedgerRecord):
    """Unvalued signed accounts can be observed without inventing simultaneous prices."""

    schema_version: Literal["conditional-ledger-v1"] = "conditional-ledger-v1"
    accounting_scope: Literal["authored-fills-and-event-schedule"] = (
        "authored-fills-and-event-schedule"
    )
    at: AwareDatetime
    initial_cash_usd: Positive
    cash_usd: Amount
    positions: Annotated[tuple[Position, ...], Field(max_length=2048)]
    claims: Annotated[tuple[CashClaim, ...], Field(max_length=2048)]
    fees_usd: Nonnegative
    applied_phases: Annotated[tuple[AppliedPhase, ...], Field(max_length=6144)]

    @field_validator("initial_cash_usd")
    @classmethod
    def initial_precision(cls, value: Decimal) -> Decimal:
        """Saved states retain the same initial-cash precision limit as fresh replay."""
        LedgerInput.bounded_precision(value)
        return value

    @model_validator(mode="after")
    def coherent_inventory(self) -> Self:
        """Saved states cannot duplicate signed inventory or retain already settled claims."""
        if len({p.security_id for p in self.positions}) != len(self.positions):
            raise ValueError("Position identities must be unique")
        if len({claim.event_id for claim in self.claims}) != len(self.claims):
            raise ValueError("Claim identities must be unique")
        phases = {(phase.event_id, phase.phase) for phase in self.applied_phases}
        if len(phases) != len(self.applied_phases):
            raise ValueError("Applied phase identities must be unique")
        if any(phase.occurred_at > self.at for phase in self.applied_phases):
            raise ValueError("Applied phases cannot be in the future")
        if any(
            claim.pay_at <= self.at
            or (claim.event_id, "effective") not in phases
            or (claim.event_id, "payment") in phases
            for claim in self.claims
        ):
            raise ValueError("Outstanding claims require an applied but unpaid entitlement")
        return self


class LedgerSnapshot(LedgerState):
    """Complete conditional NAV uses aggregate cash, not segregated collateral buying power."""

    nav_usd: Amount
    total_return: Amount

    @model_validator(mode="after")
    def coherent_return(self) -> Self:
        """Reloaded performance retains the pre-trade cash denominator and fixed arithmetic."""
        try:
            with localcontext(accounting_context()):
                if self.total_return != self.nav_usd / self.initial_cash_usd - 1:
                    raise ValueError("Return does not match NAV and initial pre-trade cash")
        except DecimalException:
            raise ValueError("Saved return exceeds supported arithmetic bounds") from None
        return self
