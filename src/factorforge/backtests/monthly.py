"""Trusted monthly raw-price strategy execution retains admission, funding and complete paths."""

import hashlib
import json
import platform
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from factorforge.backtests.accounting import account_at
from factorforge.backtests.admission import MonthlyAdmission, admit_monthly
from factorforge.backtests.funding import (
    CollateralObservation,
    FundingPlan,
    FundingRequest,
    SignedNotional,
    exact_accounting,
    exact_quantity,
    observe_collateral,
    solve_post_fee,
)
from factorforge.backtests.performance import compute_performance
from factorforge.data.artifacts import ArtifactStore, reference
from factorforge.data.monthly_signals import assemble_monthly_signals
from factorforge.domain.accounting import ConditionalFill, LedgerSnapshot, PriceMark
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.calendar import FormationPlan, TradingSession, plan_formations
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Digest, Identifier
from factorforge.domain.monthly_signals import MonthlyAssembly, MonthlySignalRequest
from factorforge.domain.performance import (
    ExecutionBatch,
    Instant,
    NavObservation,
    PerformancePath,
    PerformanceReport,
    Positive,
    RiskFreeObservation,
)
from factorforge.domain.raw_market import BorrowGrant, MarketQuote
from factorforge.domain.raw_strategy import RawStrategySpec
from factorforge.domain.targets import AllocationTemplate, PositionWeight, Rational
from factorforge.factors.targets import build_allocation

CODE_FILES = (
    "backtests/monthly.py",
    "backtests/admission.py",
    "backtests/accounting.py",
    "backtests/funding.py",
    "backtests/performance.py",
    "data/artifacts.py",
    "data/monthly_signals.py",
    "data/point_in_time.py",
    "data/raw_market.py",
    "domain/accounting.py",
    "domain/artifacts.py",
    "domain/calendar.py",
    "domain/datasets.py",
    "domain/errors.py",
    "domain/factors.py",
    "domain/formula.py",
    "domain/monthly_signals.py",
    "domain/performance.py",
    "domain/raw_market.py",
    "domain/raw_strategy.py",
    "domain/targets.py",
    "factors/targets.py",
)


def _fail(code: str) -> ResearchError:
    """Execution failures expose a stable code without private data or host diagnostics."""
    return ResearchError(code, "Monthly strategy could not complete its declared execution.", 422)


def _rational(value: Fraction) -> Rational:
    """Only bounded exact arithmetic values enter the existing canonical rational contract."""
    return Rational(numerator=str(value.numerator), denominator=str(value.denominator))


def _publish(store: ArtifactStore, raw: bytes, media_type: str) -> ArtifactRef:
    """Verify every returned artifact component instead of trusting publication metadata."""
    expected = reference(raw, media_type, 64 * 1024 * 1024)
    observed = ArtifactRef.model_validate(store.put(raw, media_type=media_type))
    if observed != expected:
        raise _fail("MONTHLY_OUTPUT_IDENTITY")
    return observed


def _put(store: ArtifactStore, value: Contract) -> ArtifactRef:
    """Publish canonical evidence through the strict output identity boundary."""
    return _publish(store, value.canonical_bytes(), "application/json")


class MonthlyRequest(Contract):
    """The capital denominator and controller clock are bound separately from strategy identity."""

    schema_version: Literal["monthly-backtest-request-v1"] = "monthly-backtest-request-v1"
    spec: RawStrategySpec
    initial_cash_usd: Positive
    evaluated_at: Instant

    @model_validator(mode="after")
    def supported_cash(self) -> Self:
        """Initial cash must fit exact ledger input precision before any admission I/O."""
        exact_quantity(Fraction(self.initial_cash_usd))
        return self


class CodeArtifact(Contract):
    """Trusted checkout source bytes are evidence, never code loaded from a stored artifact."""

    module: str
    artifact: ArtifactRef


class MonthlyPrepared(Contract):
    """A prepared record exists before any signal, allocation or account calculation starts."""

    schema_version: Literal["monthly-backtest-prepared-v1"] = "monthly-backtest-prepared-v1"
    request_ref: ArtifactRef
    admission_ref: ArtifactRef
    code: tuple[CodeArtifact, ...]
    environment_ref: ArtifactRef


class FormationReceipt(Contract):
    """The engine retains the source-selected rows and allocation fixed at each formation."""

    assembly: MonthlyAssembly
    allocation: AllocationTemplate
    missing_signal: Literal["fail", "exclude_at_formation"]

    @model_validator(mode="after")
    def matching_input(self) -> Self:
        """A saved allocation cannot be attached to another source-selected panel."""
        inputs = self.assembly.cross_section.model_dump(mode="json")
        inputs["universe"] = sorted(inputs["universe"])
        inputs["observations"] = sorted(inputs["observations"], key=lambda row: row["security_id"])
        inputs["missing_signal"] = self.missing_signal
        digest = hashlib.sha256(
            json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.allocation.input_sha256 != digest:
            raise ValueError("Allocation must bind its selected cross-section")
        return self


class AccountObservation(Contract):
    """Every required observation retains exact ledger and failed collateral evidence."""

    at: Instant
    phase: Identifier
    snapshot: LedgerSnapshot
    marks: Annotated[tuple[PriceMark, ...], Field(max_length=8)]
    collateral: CollateralObservation
    loan_refs: Annotated[tuple[Identifier, ...], Field(max_length=8)]

    @model_validator(mode="after")
    def consistent_account(self) -> Self:
        """Saved clocks, NAV and cash agree between ledger and reserve observations."""
        if (
            self.at != self.snapshot.at
            or Fraction(self.snapshot.nav_usd) != self.collateral.nav_usd.as_fraction()
            or Fraction(self.snapshot.cash_usd) != self.collateral.cash_usd.as_fraction()
        ):
            raise ValueError("Observation clock or collateral account differs")
        return self


class MonthlyBatch(Contract):
    """A generated atomic batch binds its exact sizing and all emitted fill identities."""

    batch_id: Identifier
    at: Instant
    purpose: Literal["rebalance", "liquidate"]
    funding: FundingPlan
    fill_ids: Annotated[tuple[Identifier, ...], Field(max_length=8)]
    allocation_sha256: Digest | None
    execution: ExecutionBatch

    @model_validator(mode="after")
    def coherent_batch(self) -> Self:
        """Execution summaries retain the exact request, clock and solved total notional."""
        if (
            self.batch_id != self.execution.batch_id
            or self.at != self.execution.executed_at
            or self.purpose != self.funding.request.purpose
            or (self.purpose == "rebalance") != (self.allocation_sha256 is not None)
            or len(set(self.fill_ids)) != len(self.fill_ids)
            or Fraction(self.execution.absolute_notional_usd)
            != self.funding.absolute_trade_notional_usd.as_fraction()
            or Fraction(self.execution.pre_trade_nav_usd)
            != self.funding.request.pre_trade_nav_usd.as_fraction()
        ):
            raise ValueError("Batch summary must match its exact funded request")
        return self


class MonthlyRun(Contract):
    """A terminal run preserves the requested denominator and cannot shorten a failed sample."""

    schema_version: Literal["monthly-backtest-run-v1"] = "monthly-backtest-run-v1"
    scope: Literal["original-monthly-raw-price-simulator"] = "original-monthly-raw-price-simulator"
    request: MonthlyRequest
    request_ref: ArtifactRef
    admission_ref: ArtifactRef | None
    prepared_ref: ArtifactRef | None
    status: Literal["completed", "failed"]
    failure_code: Identifier | None
    failure_at: Instant | None
    plans: Annotated[tuple[FormationPlan, ...], Field(max_length=12)]
    skipped_plans: Annotated[tuple[FormationPlan, ...], Field(max_length=12)]
    session_closes: Annotated[tuple[Instant, ...], Field(max_length=512)]
    formations: Annotated[tuple[FormationReceipt, ...], Field(max_length=12)]
    observations: Annotated[tuple[AccountObservation, ...], Field(max_length=1050)]
    batches: Annotated[tuple[MonthlyBatch, ...], Field(max_length=13)]
    fills: Annotated[tuple[ConditionalFill, ...], Field(max_length=2048)]
    path: PerformancePath | None
    performance: PerformanceReport | None
    benchmark_path: PerformancePath | None
    benchmark: PerformanceReport | None

    @model_validator(mode="after")
    def terminal_coherence(self) -> Self:
        """Only complete declared close paths and archived preparation can claim completion."""
        if (
            reference(self.request.canonical_bytes(), "application/json", 64 * 1024 * 1024)
            != self.request_ref
        ):
            raise ValueError("Request reference differs from the retained request")
        if (self.formations or self.observations or self.batches or self.fills) and (
            self.admission_ref is None or self.prepared_ref is None
        ):
            raise ValueError("Economic trace requires retained admission and preparation")
        complete = self.status == "completed"
        if complete != (self.failure_code is None):
            raise ValueError("Failure code must match terminal status")
        if complete:
            if any(
                item is None
                for item in (
                    self.admission_ref,
                    self.prepared_ref,
                    self.path,
                    self.performance,
                    self.benchmark_path,
                    self.benchmark,
                )
            ):
                raise ValueError("Completed execution needs every lineage and performance record")
            assert self.path is not None and self.performance is not None
            assert self.benchmark_path is not None and self.benchmark is not None
            if (
                self.path.session_closes != self.session_closes
                or self.path.sha256 != self.performance.path_sha256
                or self.benchmark_path.sha256 != self.benchmark.path_sha256
                or self.benchmark_path.session_closes != self.session_closes
                or self.failure_at is not None
            ):
                raise ValueError("Completed performance must match the full declared path")
            observed_closes = tuple(
                NavObservation(at=row.at, nav_usd=row.snapshot.nav_usd)
                for row in self.observations
                if row.phase in {"baseline_close", "close", "after_liquidation_close"}
            )
            if observed_closes != (self.path.inception, *self.path.closes):
                raise ValueError("Completed metrics require the actual retained account closes")
            if (
                not self.observations
                or self.observations[-1].phase != "after_liquidation_close"
                or any(row.signed_shares for row in self.observations[-1].snapshot.positions)
                or any(row.collateral.status != "funded" for row in self.observations)
            ):
                raise ValueError("Completed execution requires funded observations and liquidation")
        elif any(
            item is not None
            for item in (
                self.path,
                self.performance,
                self.benchmark_path,
                self.benchmark,
            )
        ):
            raise ValueError("Failed execution cannot retain completed full-sample metrics")
        if tuple(fill.fill_id for fill in self.fills) != tuple(
            identity for batch in self.batches for identity in batch.fill_ids
        ):
            raise ValueError("Generated fills must exactly match the ordered batch inventory")
        return self

    @model_validator(mode="after")
    def source_and_trade_lineage(self) -> Self:
        """Source-selected formula choices and generated fills close over this exact strategy."""
        spec = self.request.spec
        allocations = {}
        for formation in self.formations:
            selected = formation.assembly.request
            if (
                formation.assembly.source_ref != spec.universe.table.artifact
                or selected.formula != spec.formula
                or selected.bindings != tuple(row.monthly_binding() for row in spec.signal_inputs)
                or selected.formation_lag_months != spec.timing.formation_lag_months
                or selected.formation not in self.plans
                or formation.allocation.allocation != spec.portfolio.allocation
                or formation.missing_signal != spec.policies.missing_signal
            ):
                raise ValueError("Formation evidence differs from the declared strategy")
            allocations[formation.allocation.sha256] = formation.allocation
        fills = {row.fill_id: row for row in self.fills}
        if len(fills) != len(self.fills) or len({row.batch_id for row in self.batches}) != len(
            self.batches
        ):
            raise ValueError("Generated fill and batch identities must be unique")
        for batch in self.batches:
            if batch.funding.request.costs != spec.costs:
                raise ValueError("Batch costs differ from the strategy")
            if batch.allocation_sha256 is not None:
                allocation = allocations.get(batch.allocation_sha256)
                if allocation is None or allocation.formation.trade_at != batch.at:
                    raise ValueError("Batch requires its actual formation allocation")
                weights = {row.security_id: row.weight for row in allocation.positions}
                if weights != {
                    row.security_id: row.weight for row in batch.funding.request.target_weights
                }:
                    raise ValueError("Funded weights differ from the selected allocation")
            expected = {
                row.security_id: row.trade_notional_usd.as_fraction()
                for row in batch.funding.positions
                if row.trade_notional_usd.as_fraction()
            }
            emitted = [fills[identity] for identity in batch.fill_ids]
            if (
                len(emitted) != len(expected)
                or any(row.executed_at != batch.at for row in emitted)
                or {
                    row.security_id: Fraction(row.signed_quantity) * Fraction(row.quote.price_usd)
                    for row in emitted
                }
                != expected
            ):
                raise ValueError("Generated fills differ from exact solved trade notionals")
        return self


@dataclass
class _Execution:
    """Private mutable execution state is never accepted from a caller or loaded result."""

    request: MonthlyRequest
    admitted: MonthlyAdmission
    plans: tuple[FormationPlan, ...] = ()
    skipped: tuple[FormationPlan, ...] = ()
    sessions: tuple[TradingSession, ...] = ()
    at: datetime | None = None
    holdings: dict[str, Fraction] = field(default_factory=dict)
    cash: Fraction = Fraction(0)
    fees: Fraction = Fraction(0)
    loans: dict[str, BorrowGrant] = field(default_factory=dict)
    quotes: dict[tuple[str, datetime], MarketQuote] = field(default_factory=dict)
    formations: list[FormationReceipt] = field(default_factory=list)
    observations: list[AccountObservation] = field(default_factory=list)
    batches: list[MonthlyBatch] = field(default_factory=list)
    fills: list[ConditionalFill] = field(default_factory=list)
    closes: list[NavObservation] = field(default_factory=list)


def _prepare(store: ArtifactStore, request: ArtifactRef, admission: ArtifactRef) -> ArtifactRef:
    """Archive fixed trusted module bytes and package versions before the numerical loop."""
    root = Path(__file__).resolve().parents[1]
    code = []
    for name in CODE_FILES:
        raw = (root / name).read_bytes()
        if len(raw) > 1024 * 1024:
            raise _fail("MONTHLY_CODE_LIMIT")
        code.append(CodeArtifact(module=name, artifact=_publish(store, raw, "text/x-python")))
    environment = json.dumps(
        {
            "schema_version": "monthly-environment-v1",
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
            "packages": {name: version(name) for name in ("pydantic", "polars")},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    environment_ref = _publish(store, environment, "application/json")
    return _put(
        store,
        MonthlyPrepared(
            request_ref=request,
            admission_ref=admission,
            code=tuple(code),
            environment_ref=environment_ref,
        ),
    )


def _schedule(state: _Execution) -> None:
    """Derive the complete requested chronology before observing any strategy outcome."""
    spec, calendar = state.request.spec, state.admitted.calendar
    if len(calendar.sessions) > 512:
        raise _fail("MONTHLY_SESSION_LIMIT")
    plans = plan_formations(
        calendar, spec.timing, start=spec.evaluation.sample_start, end=spec.evaluation.sample_end
    )
    if not plans or len(plans) > 12:
        raise _fail("MONTHLY_FORMATION_LIMIT")
    sessions = tuple(
        row
        for row in calendar.sessions
        if (spec.evaluation.sample_start <= row.session_date <= spec.evaluation.sample_end)
    )
    if (
        len(sessions) < 2
        or sessions[0].session_date != spec.evaluation.sample_start
        or sessions[-1].session_date != spec.evaluation.sample_end
        or sessions[0].closes_at != plans[0].formation_at
        or state.request.evaluated_at < sessions[-1].closes_at
    ):
        raise _fail("MONTHLY_SAMPLE_INVALID")
    state.sessions, state.plans = sessions, plans
    terminal = sessions[-1].closes_at
    state.skipped = tuple(plan for plan in plans if plan.trade_at > terminal)
    cells = (
        len(state.admitted.market.security_ids)
        * sum(binding.history_observations for binding in spec.signal_inputs)
        * len(plans)
    )
    if cells > 100000:
        raise _fail("MONTHLY_CELL_LIMIT")
    state.quotes = {(row.security_id, row.observed_at): row for row in state.admitted.market.quotes}
    if state.admitted.market.actions:
        raise _fail("MONTHLY_ACTIONS_UNSUPPORTED")
    if (
        state.admitted.market.coverage_start > sessions[0].closes_at
        or state.admitted.market.coverage_end < terminal
    ):
        raise _fail("MONTHLY_MARKET_COVERAGE")


def _marks(
    state: _Execution, at: datetime, phase: str, required: set[str]
) -> tuple[PriceMark, ...]:
    """Only exact-time known raw quotes can value held positions or size declared targets."""
    result = []
    for security in state.admitted.market.security_ids:
        quote = state.quotes.get((security, at))
        valid = quote is not None and quote.phase == phase and quote.available_at <= at
        if security in required and not valid:
            raise _fail("MONTHLY_QUOTE_MISSING_OR_UNAVAILABLE")
        if valid:
            assert quote is not None
            result.append(quote.ledger_mark())
    if required - set(state.admitted.market.security_ids):
        raise _fail("MONTHLY_SECURITY_UNSUPPORTED")
    return tuple(result)


def _loan(state: _Execution, security: str, quantity: Fraction, at: datetime) -> BorrowGrant:
    """One explicit known grant must independently cover the entire target short position."""
    grants = tuple(
        row
        for row in state.admitted.market.borrow_grants
        if (
            row.security_id == security
            and row.available_at <= at
            and row.valid_from <= at <= row.valid_through
            and Fraction(row.maximum_short_shares) >= -quantity
        )
    )
    if len(grants) != 1:
        raise _fail("MONTHLY_BORROW_UNAVAILABLE_OR_AMBIGUOUS")
    return grants[0]


def _observe(state: _Execution, at: datetime, phase: str, mark_phase: str) -> AccountObservation:
    """Retain failed reserve evidence and compare ledger replay with exact independent balances."""
    state.at = at
    held = {security for security, quantity in state.holdings.items() if quantity}
    marks = _marks(state, at, mark_phase, held)
    prices = {row.security_id: Fraction(row.price_usd) for row in marks}
    notionals = tuple(
        SignedNotional(
            security_id=security,
            notional_usd=_rational(
                state.holdings.get(security, Fraction(0)) * prices.get(security, 0)
            ),
        )
        for security in state.admitted.market.security_ids
    )
    for row in notionals:
        exact_accounting(row.notional_usd.as_fraction())
    expected_nav = state.cash
    for row in notionals:
        expected_nav += row.notional_usd.as_fraction()
        exact_accounting(expected_nav)
    snapshot = account_at(
        initial_cash=state.request.initial_cash_usd,
        start_at=state.sessions[0].closes_at,
        at=at,
        fills=tuple(state.fills),
        actions=(),
        marks=marks,
        costs=state.request.spec.costs,
    )
    if (
        Fraction(snapshot.cash_usd) != state.cash
        or Fraction(snapshot.fees_usd) != state.fees
        or Fraction(snapshot.nav_usd) != expected_nav
        or {
            row.security_id: Fraction(row.signed_shares)
            for row in snapshot.positions
            if row.signed_shares
        }
        != {key: value for key, value in state.holdings.items() if value}
    ):
        raise _fail("MONTHLY_LEDGER_DISAGREEMENT")
    collateral = observe_collateral(cash_usd=snapshot.cash_usd, notionals=notionals)
    observation = AccountObservation(
        at=at,
        phase=phase,
        snapshot=snapshot,
        marks=marks,
        collateral=collateral,
        loan_refs=tuple(sorted(row.source_id for row in state.loans.values())),
    )
    state.observations.append(observation)
    if collateral.status != "funded":
        assert collateral.failure_code is not None
        raise _fail(collateral.failure_code)
    for security, quantity in state.holdings.items():
        if quantity < 0:
            grant = state.loans.get(security)
            if (
                grant is None
                or not grant.valid_from <= at <= grant.valid_through
                or grant.available_at > at
                or Fraction(grant.maximum_short_shares) < -quantity
            ):
                raise _fail("MONTHLY_BORROW_EXPIRED_OR_INSUFFICIENT")
    return observation


def _formation(state: _Execution, plan: FormationPlan) -> AllocationTemplate:
    """Select only formation-known rows and retain the exact Polars allocation before trade."""
    spec = state.request.spec
    request = MonthlySignalRequest(
        formation=plan,
        formula=spec.formula,
        formation_lag_months=spec.timing.formation_lag_months,
        bindings=tuple(row.monthly_binding() for row in spec.signal_inputs),
        capitalization_binding=None,
        freshness=spec.policies.freshness,
        revision_policy="latest_available_then_revision_reject_conflicts",
    )
    assembly = assemble_monthly_signals(spec.universe.table.artifact, state.admitted.store, request)
    if len(assembly.cross_section.universe) > 8 or set(assembly.cross_section.universe) - set(
        state.admitted.market.security_ids
    ):
        raise _fail("MONTHLY_SECURITY_UNSUPPORTED")
    allocation = build_allocation(
        assembly.cross_section,
        spec.portfolio.allocation,
        missing_signal=spec.policies.missing_signal,
    )
    state.formations.append(
        FormationReceipt(
            assembly=assembly, allocation=allocation, missing_signal=spec.policies.missing_signal
        )
    )
    return allocation


def _batch(
    state: _Execution,
    at: datetime,
    before: AccountObservation,
    allocation: AllocationTemplate | None,
) -> None:
    """Preflight the entire exact atomic batch before adding any generated ledger fill."""
    weights = (
        ()
        if allocation is None
        else tuple(
            PositionWeight(security_id=row.security_id, weight=row.weight)
            for row in allocation.positions
        )
    )
    required = {row.security_id for row in weights if row.weight.as_fraction()}
    required.update(key for key, value in state.holdings.items() if value)
    marks = _marks(state, at, "close" if allocation is None else "open", required)
    prices = {row.security_id: Fraction(row.price_usd) for row in marks}
    quotes = {row.security_id: row for row in marks}
    old = tuple(
        SignedNotional(security_id=key, notional_usd=_rational(quantity * prices[key]))
        for key, quantity in sorted(state.holdings.items())
        if quantity
    )
    funding = solve_post_fee(
        FundingRequest(
            pre_trade_nav_usd=_rational(Fraction(before.snapshot.nav_usd)),
            old_notionals=old,
            target_weights=weights,
            costs=state.request.spec.costs,
            purpose="liquidate" if allocation is None else "rebalance",
        )
    )
    batch_id = f"batch-{len(state.batches):04d}"
    staged_fills = []
    new_holdings = {}
    new_loans = {}
    cash, fees = state.cash, state.fees
    costs = state.request.spec.costs
    for row in funding.positions:
        security = row.security_id
        target = row.target_notional_usd.as_fraction()
        quantity = target / prices[security] if target else Fraction(0)
        exact_quantity(quantity)
        trade = quantity - state.holdings.get(security, Fraction(0))
        decimal_trade = exact_quantity(trade)
        new_holdings[security] = quantity
        if quantity < 0:
            new_loans[security] = _loan(state, security, quantity, at)
        if not trade:
            continue
        notional = trade * prices[security]
        commission = abs(notional) * Fraction(costs.commission_bps, 10000)
        slippage = abs(notional) * Fraction(costs.slippage_bps, 10000)
        for number in (
            notional,
            commission,
            slippage,
            commission + slippage,
            cash - notional,
            cash - notional - commission,
            cash - notional - commission - slippage,
            fees + commission + slippage,
        ):
            exact_accounting(number)
        cash -= notional + commission + slippage
        fees += commission + slippage
        staged_fills.append(
            ConditionalFill(
                fill_id=f"{batch_id}-{security}",
                security_id=security,
                signed_quantity=decimal_trade,
                executed_at=at,
                quote=quotes[security],
            )
        )
    exact_accounting(funding.absolute_trade_notional_usd.as_fraction())
    if len(state.fills) + len(staged_fills) > 2048:
        raise _fail("MONTHLY_FILL_LIMIT")
    state.cash, state.fees, state.holdings, state.loans = cash, fees, new_holdings, new_loans
    state.fills.extend(staged_fills)
    execution = ExecutionBatch(
        batch_id=batch_id,
        executed_at=at,
        absolute_notional_usd=exact_accounting(funding.absolute_trade_notional_usd.as_fraction()),
        pre_trade_nav_usd=before.snapshot.nav_usd,
    )
    state.batches.append(
        MonthlyBatch(
            batch_id=batch_id,
            at=at,
            purpose="liquidate" if allocation is None else "rebalance",
            funding=funding,
            fill_ids=tuple(row.fill_id for row in staged_fills),
            allocation_sha256=allocation.sha256 if allocation else None,
            execution=execution,
        )
    )
    after = _observe(
        state,
        at,
        "after_liquidation_close" if allocation is None else "after_entry",
        "close" if allocation is None else "open",
    )
    if Fraction(after.snapshot.nav_usd) != funding.sizing_nav_usd.as_fraction():
        raise _fail("MONTHLY_FUNDED_BATCH_DISAGREEMENT")


def _loop(state: _Execution) -> None:
    """Every calendar open/close remains in the chronology even when there is no trade."""
    _schedule(state)
    state.cash = Fraction(state.request.initial_cash_usd)
    baseline = state.sessions[0].closes_at
    _observe(state, baseline, "baseline_close", "close")
    trades: dict[datetime, AllocationTemplate] = {}
    by_formation = {plan.formation_at: plan for plan in state.plans if plan not in state.skipped}
    trades[state.plans[0].trade_at] = _formation(state, state.plans[0])
    for session in state.sessions[1:]:
        allocation = trades.get(session.opens_at)
        before = _observe(state, session.opens_at, "before_entry" if allocation else "open", "open")
        if allocation is not None:
            _batch(state, session.opens_at, before, allocation)
        terminal = session == state.sessions[-1]
        close = _observe(
            state, session.closes_at, "before_liquidation" if terminal else "close", "close"
        )
        if terminal:
            _batch(state, session.closes_at, close, None)
            close = state.observations[-1]
        state.closes.append(NavObservation(at=session.closes_at, nav_usd=close.snapshot.nav_usd))
        plan = by_formation.get(session.closes_at)
        if plan is not None and not terminal:
            trades[plan.trade_at] = _formation(state, plan)


def _metrics(
    state: _Execution,
) -> tuple[PerformancePath, PerformanceReport, PerformancePath, PerformanceReport]:
    """Complete exact comparison intervals cannot shorten or influence the formation sample."""
    clocks = tuple(row.closes_at for row in state.sessions)
    index = {
        (row.series_id, row.start_at, row.end_at): row for row in state.admitted.intervals.rows
    }
    rates = []
    benchmark_closes = []
    benchmark_nav = Fraction(state.request.initial_cash_usd)
    for start, end in pairwise(clocks):
        risk_free = index.get(("risk_free", start, end))
        benchmark = index.get(("benchmark", start, end))
        if (
            risk_free is None
            or benchmark is None
            or risk_free.available_at > state.request.evaluated_at
            or benchmark.available_at > state.request.evaluated_at
        ):
            raise _fail("MONTHLY_COMPARISON_INTERVAL_UNAVAILABLE")
        rates.append(
            RiskFreeObservation(
                start_at=start,
                end_at=end,
                cumulative_return=risk_free.cumulative_return,
            )
        )
        benchmark_nav *= 1 + Fraction(benchmark.cumulative_return)
        benchmark_closes.append(NavObservation(at=end, nav_usd=exact_accounting(benchmark_nav)))
    path = PerformancePath(
        initial_capital_usd=state.request.initial_cash_usd,
        baseline_at=clocks[0],
        inception=NavObservation(at=clocks[0], nav_usd=state.request.initial_cash_usd),
        session_closes=clocks,
        closes=tuple(state.closes),
        external_cash_flows=False,
    )
    benchmark_path = path.model_copy(update={"closes": tuple(benchmark_closes)})
    performance = compute_performance(
        path,
        annualization=state.request.spec.evaluation.annualization,
        risk_free=tuple(rates),
        execution_batches=tuple(row.execution for row in state.batches),
    )
    benchmark_report = compute_performance(
        benchmark_path,
        annualization=state.request.spec.evaluation.annualization,
        risk_free=tuple(rates),
        execution_batches=(),
    )
    return path, performance, benchmark_path, benchmark_report


def run_monthly(
    spec: RawStrategySpec,
    store: ArtifactStore,
    *,
    initial_cash_usd: Decimal,
    evaluated_at: datetime,
) -> MonthlyRun:
    """Admit source bytes and execute the fixed bounded strategy with retained failure evidence."""
    try:
        request = MonthlyRequest(
            spec=spec, initial_cash_usd=initial_cash_usd, evaluated_at=evaluated_at
        )
    except (ValueError, TypeError):
        raise _fail("MONTHLY_REQUEST_INVALID") from None
    request_ref = _put(store, request)
    admission_ref = prepared_ref = None
    state = None
    failure = None
    metrics = None
    try:
        admitted = admit_monthly(request.spec, store, evaluated_at=request.evaluated_at)
        admission_ref = _put(store, admitted.receipt)
        prepared_ref = _prepare(store, request_ref, admission_ref)
        state = _Execution(request=request, admitted=admitted)
        _loop(state)
        metrics = _metrics(state)
    except ResearchError as error:
        failure = error.code
    except Exception:
        failure = "MONTHLY_EXECUTION_FAILED"
    result = MonthlyRun(
        request=request,
        request_ref=request_ref,
        admission_ref=admission_ref,
        prepared_ref=prepared_ref,
        status="failed" if failure else "completed",
        failure_code=failure,
        failure_at=state.at if failure and state else None,
        plans=state.plans if state else (),
        skipped_plans=state.skipped if state else (),
        session_closes=tuple(row.closes_at for row in state.sessions) if state else (),
        formations=tuple(state.formations) if state else (),
        observations=tuple(state.observations) if state else (),
        batches=tuple(state.batches) if state else (),
        fills=tuple(state.fills) if state else (),
        path=metrics[0] if metrics else None,
        performance=metrics[1] if metrics else None,
        benchmark_path=metrics[2] if metrics else None,
        benchmark=metrics[3] if metrics else None,
    )
    _put(store, result)
    return result
