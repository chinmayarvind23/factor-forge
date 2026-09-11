"""Pure deterministic signed-share accounting for explicitly conditional raw-price fills."""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, DecimalException, localcontext

from pydantic import ValidationError

from factorforge.domain.accounting import (
    AppliedPhase,
    CashClaim,
    ConditionalFill,
    CorporateAction,
    LedgerCosts,
    LedgerRecord,
    LedgerSnapshot,
    LedgerState,
    Position,
    PriceMark,
    accounting_context,
    accounting_utc,
)
from factorforge.domain.errors import ResearchError

MAX_ITEMS = 2048


def _fail(code: str) -> ResearchError:
    """Keep input contents and internal arithmetic details out of typed failure messages."""
    return ResearchError(
        code, "Conditional accounting cannot produce a complete valid account.", 422
    )


def _inventory[Record: LedgerRecord](
    items: Sequence[Record], record_type: type[Record], identity: str
) -> tuple[Record, ...]:
    """Bound inventory work, revalidate nested records and collapse only exact duplicate IDs."""
    if not isinstance(items, (tuple, list)) or len(items) > MAX_ITEMS:
        raise _fail("ACCOUNTING_INPUT_INVALID")
    unique: dict[str, Record] = {}
    for raw in items:
        item = record_type.model_validate(raw)
        key = str(getattr(item, identity))
        if key in unique and unique[key] != item:
            raise _fail("ACCOUNTING_IDENTITY_CONFLICT")
        unique[key] = item
    return tuple(unique[key] for key in sorted(unique))


def _timeline(
    fills: tuple[ConditionalFill, ...],
    actions: tuple[CorporateAction, ...],
    start: datetime,
) -> list[tuple[datetime, int, str, ConditionalFill | CorporateAction]]:
    """Economic effects precede payments and fills; ambiguous same-security effects are rejected."""
    events: list[tuple[datetime, int, str, ConditionalFill | CorporateAction]] = []
    occupied: set[tuple[str, datetime]] = set()
    if {fill.fill_id for fill in fills} & {action.event_id for action in actions}:
        raise _fail("ACCOUNTING_IDENTITY_CONFLICT")
    for action in actions:
        key = (action.security_id, action.effective_at)
        if key in occupied:
            raise _fail("ACCOUNTING_AMBIGUOUS_EVENT_ORDER")
        occupied.add(key)
        events.append((action.effective_at, 0, action.event_id, action))
        if action.pay_at is not None:
            events.append((action.pay_at, 1, action.event_id, action))
    events.extend((fill.executed_at, 2, fill.fill_id, fill) for fill in fills)
    if any(occurred < start for occurred, _, _, _ in events):
        raise _fail("ACCOUNTING_EVENT_BEFORE_START")
    return sorted(events, key=lambda item: (item[0], item[1], item[2]))


def _consistent_prices(marks: tuple[PriceMark, ...]) -> None:
    """The single-price profile rejects contradictory raw observations even across source IDs."""
    prices: dict[tuple[str, datetime], Decimal] = {}
    for mark in marks:
        key = (mark.security_id, mark.observed_at)
        if key in prices and prices[key] != mark.price_usd:
            raise _fail("ACCOUNTING_MARK_CONFLICT")
        prices[key] = mark.price_usd


def _bounded(value: Decimal) -> Decimal:
    """Stop numeric growth before an account exceeds its declared supported magnitude."""
    if not value.is_finite() or abs(value) > Decimal("1e24"):
        raise _fail("ACCOUNTING_NUMERIC_BOUND")
    return value


def _replay(
    initial: Decimal,
    start: datetime,
    at: datetime,
    fills: tuple[ConditionalFill, ...],
    actions: tuple[CorporateAction, ...],
    costs: LedgerCosts,
) -> tuple[Decimal, Decimal, dict[str, Decimal], dict[str, CashClaim], tuple[AppliedPhase, ...]]:
    """Apply each authored phase once from the initial cash account, preserving signed claims."""
    cash, fees = initial, Decimal(0)
    positions: dict[str, Decimal] = {}
    claims: dict[str, CashClaim] = {}
    exited: set[str] = set()
    phases: list[AppliedPhase] = []
    for occurred, phase, event_id, event in _timeline(fills, actions, start):
        if occurred > at:
            break
        security = event.security_id
        shares = positions.get(security, Decimal(0))
        if isinstance(event, ConditionalFill):
            if security in exited:
                raise _fail("ACCOUNTING_TRADE_AFTER_EXIT")
            notional = event.signed_quantity * event.quote.price_usd
            fee = abs(notional) * Decimal(costs.commission_bps + costs.slippage_bps) / 10000
            positions[security] = _bounded(shares + event.signed_quantity)
            cash, fees = _bounded(cash - notional - fee), _bounded(fees + fee)
        elif phase == 1:
            claim = claims.pop(event_id)
            cash = _bounded(cash + claim.signed_amount_usd)
        elif event.kind == "split":
            assert event.new_shares is not None and event.old_shares is not None
            if security in exited:
                raise _fail("ACCOUNTING_ACTION_AFTER_EXIT")
            if security in positions:
                positions[security] = _bounded(shares * event.new_shares / event.old_shares)
        else:
            if security in exited:
                raise _fail("ACCOUNTING_ACTION_AFTER_EXIT")
            if event.kind == "terminal_exit":
                if event.cash_per_share is None and shares != 0:
                    raise _fail("ACCOUNTING_UNKNOWN_EXIT")
                exited.add(security)
                if security in positions:
                    positions[security] = Decimal(0)
            if event.cash_per_share is not None:
                assert event.pay_at is not None
                claims[event_id] = CashClaim(
                    event_id=event_id,
                    security_id=security,
                    kind=event.kind,
                    signed_amount_usd=_bounded(shares * event.cash_per_share),
                    pay_at=event.pay_at,
                )
        phases.append(
            AppliedPhase(
                event_id=event_id,
                phase=("effective", "payment", "fill")[phase],
                occurred_at=occurred,
            )
        )
    return cash, fees, positions, claims, tuple(phases)


def _nav(
    cash: Decimal,
    positions: dict[str, Decimal],
    claims: dict[str, CashClaim],
    marks: tuple[PriceMark, ...],
    at: datetime,
) -> Decimal:
    """Value held shares only at exact available raw observations and outstanding fixed claims."""
    prices: dict[str, Decimal] = {}
    for mark in marks:
        if mark.observed_at == at and mark.available_at <= at:
            prices[mark.security_id] = mark.price_usd
    nav = cash + sum((claim.signed_amount_usd for claim in claims.values()), Decimal(0))
    for security, shares in sorted(positions.items()):
        if shares:
            if security not in prices:
                raise _fail("ACCOUNTING_MARK_MISSING")
            nav += shares * prices[security]
    return _bounded(nav)


def ledger_at(
    *,
    initial_cash: Decimal,
    start_at: datetime,
    at: datetime,
    fills: Sequence[ConditionalFill],
    actions: Sequence[CorporateAction],
    costs: LedgerCosts,
) -> LedgerState:
    """Replay the explicit ex-post schedule using fixed 50-digit half-even Decimal arithmetic.

    Initial cash is the pre-trade performance denominator. No external flows, reinvestment,
    price filling, collateral spending permission or nonzero ongoing carry is inferred.
    """
    try:
        start_at, at = accounting_utc(start_at), accounting_utc(at)
        if (
            not isinstance(initial_cash, Decimal)
            or not initial_cash.is_finite()
            or not Decimal(0) < initial_cash <= Decimal("1e24")
            or at < start_at
        ):
            raise _fail("ACCOUNTING_INPUT_INVALID")
        verified_fills = _inventory(fills, ConditionalFill, "fill_id")
        verified_actions = _inventory(actions, CorporateAction, "event_id")
        _consistent_prices(
            _inventory(tuple(fill.quote for fill in verified_fills), PriceMark, "source_id")
        )
        parts = initial_cash.as_tuple()
        if len(parts.digits) > 43 or not isinstance(parts.exponent, int) or parts.exponent < -18:
            raise _fail("ACCOUNTING_INPUT_INVALID")
        policy = LedgerCosts.model_validate(costs)
        with localcontext(accounting_context()):
            cash, fees, positions, claims, phases = _replay(
                initial_cash, start_at, at, verified_fills, verified_actions, policy
            )
            return LedgerState(
                at=at.astimezone(UTC),
                initial_cash_usd=initial_cash,
                cash_usd=cash,
                fees_usd=fees,
                positions=tuple(
                    Position(security_id=key, signed_shares=value)
                    for key, value in sorted(positions.items())
                ),
                claims=tuple(claims[key] for key in sorted(claims)),
                applied_phases=phases,
            )
    except (ValidationError, ValueError, TypeError):
        raise _fail("ACCOUNTING_INPUT_INVALID") from None
    except DecimalException:
        raise _fail("ACCOUNTING_NUMERIC_BOUND") from None


def account_at(
    *,
    initial_cash: Decimal,
    start_at: datetime,
    at: datetime,
    fills: Sequence[ConditionalFill],
    actions: Sequence[CorporateAction],
    marks: Sequence[PriceMark],
    costs: LedgerCosts,
) -> LedgerSnapshot:
    """Value a deterministic replay only when all held securities have exact available raw marks."""
    try:
        verified_fills = _inventory(fills, ConditionalFill, "fill_id")
        state = ledger_at(
            initial_cash=initial_cash,
            start_at=start_at,
            at=at,
            fills=verified_fills,
            actions=actions,
            costs=costs,
        )
        verified_marks = _inventory(marks, PriceMark, "source_id")
        _consistent_prices(
            _inventory(
                (*verified_marks, *(fill.quote for fill in verified_fills)), PriceMark, "source_id"
            )
        )
        with localcontext(accounting_context()):
            nav = _nav(
                state.cash_usd,
                {p.security_id: p.signed_shares for p in state.positions},
                {claim.event_id: claim for claim in state.claims},
                verified_marks,
                state.at,
            )
            return LedgerSnapshot(
                **state.model_dump(), nav_usd=nav, total_return=_bounded(nav / initial_cash - 1)
            )
    except (ValidationError, ValueError, TypeError):
        raise _fail("ACCOUNTING_INPUT_INVALID") from None
    except DecimalException:
        raise _fail("ACCOUNTING_NUMERIC_BOUND") from None
