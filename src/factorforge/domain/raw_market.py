"""Bounded original market inputs distinguish raw observations, event coverage and short loans."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from factorforge.domain.accounting import CorporateAction, LedgerInput, Positive, PriceMark
from factorforge.domain.factors import Contract, Identifier
from factorforge.domain.performance import Amount, Instant


class MarketQuote(PriceMark):
    """An opening or closing observation retains the existing exact raw USD quote contract."""

    phase: Literal["open", "close"]

    def ledger_mark(self) -> PriceMark:
        """Project a revalidated quote while preserving every ledger price and timing field."""
        value = MarketQuote.model_validate(self)
        return PriceMark.model_validate(value.model_dump(exclude={"phase"}))


class BorrowGrant(LedgerInput):
    """Original loan permission carries a finite exact share limit and explicit zero carry."""

    source_id: Identifier
    security_id: Identifier
    available_at: Instant
    valid_from: Instant
    valid_through: Instant
    maximum_short_shares: Positive
    annual_borrow_bps: Annotated[int, Field(ge=0, le=0)]
    permission: Literal["original_fixture_short_loan"]

    @model_validator(mode="after")
    def ordered_term(self) -> Self:
        """A loan covers a nonempty closed interval; availability is checked when it is consumed."""
        if self.valid_from >= self.valid_through:
            raise ValueError("Borrow term must have a later expiry")
        return self


class RawMarketSource(Contract):
    """Coverage assertions never substitute for per-calendar observation and funding checks."""

    schema_version: Literal["raw-market-source-v1"] = "raw-market-source-v1"
    coverage_start: Instant
    coverage_end: Instant
    security_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=8)]
    quotes: Annotated[tuple[MarketQuote, ...], Field(max_length=8192)]
    actions: Annotated[tuple[CorporateAction, ...], Field(max_length=2048)]
    borrow_grants: Annotated[tuple[BorrowGrant, ...], Field(max_length=2048)]
    corporate_action_coverage: Literal["complete_explicit_events"]
    terminal_exit_coverage: Literal["complete_explicit_events"]

    @model_validator(mode="after")
    def coherent_inventory(self) -> Self:
        """Reject duplicate identities, ambiguous quote instants and rows outside asserted scope."""
        ids = set(self.security_ids)
        if not ids or len(ids) != len(self.security_ids) or self.security_ids != tuple(sorted(ids)):
            raise ValueError("Market security inventory must be unique and sorted")
        if self.coverage_start >= self.coverage_end:
            raise ValueError("Market coverage must be a nonempty interval")
        for rows in (self.quotes, self.actions, self.borrow_grants):
            if any(row.security_id not in ids for row in rows):
                raise ValueError("Market row security is outside declared coverage")
        for rows in (self.quotes, self.borrow_grants):
            if len({row.source_id for row in rows}) != len(rows):
                raise ValueError("Source row identifiers must be unique within each role")
        if len({row.event_id for row in self.actions}) != len(self.actions):
            raise ValueError("Action identifiers must be unique")
        if len({(row.security_id, row.observed_at) for row in self.quotes}) != len(self.quotes):
            raise ValueError("A security has only one quote at each observed instant")
        if any(
            not self.coverage_start <= row.observed_at <= self.coverage_end for row in self.quotes
        ) or any(
            not self.coverage_start <= row.effective_at <= self.coverage_end for row in self.actions
        ):
            raise ValueError("Price and action clocks must lie inside source coverage")
        return self


class IntervalReturn(Contract):
    """Comparison rows declare cumulative decimal returns for exact close-to-close intervals."""

    source_id: Identifier
    series_id: Literal["benchmark", "risk_free"]
    start_at: Instant
    end_at: Instant
    available_at: Instant
    cumulative_return: Annotated[Amount, Field(ge=-1)]

    @model_validator(mode="after")
    def forward_interval(self) -> Self:
        """Publication can differ from period end; consumption checks its known-at time."""
        if self.start_at >= self.end_at:
            raise ValueError("Comparison return interval must be forward")
        return self


class IntervalSource(Contract):
    """At most two complete comparison series fit the first 512-session original profile."""

    schema_version: Literal["interval-returns-v1"] = "interval-returns-v1"
    rows: Annotated[tuple[IntervalReturn, ...], Field(max_length=1022)]

    @model_validator(mode="after")
    def unique_intervals(self) -> Self:
        """Duplicate source IDs or series intervals cannot silently replace reference returns."""
        if len({row.source_id for row in self.rows}) != len(self.rows) or len(
            {(row.series_id, row.start_at, row.end_at) for row in self.rows}
        ) != len(self.rows):
            raise ValueError("Comparison return rows must have unique identities and intervals")
        return self
