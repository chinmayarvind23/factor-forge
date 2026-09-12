"""A distinct monthly raw-price FactorSpec declares supported execution without v2 migration."""

import ast
import hashlib
import json
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from factorforge.domain.accounting import LedgerCosts
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import (
    AllocationSpec,
    Contract,
    DatasetLink,
    Identifier,
    InputBinding,
    TableReference,
    TimingSpec,
    Unit,
    UniverseSpec,
    _dimensions,
    _formula_dimensions,
)
from factorforge.domain.formula import parse_formula
from factorforge.domain.monthly_signals import MonthlyBinding, subtract_civil_months

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_CLOSURE_BYTES = 64 * 1024 * 1024


def _table(table: TableReference, schema: str) -> None:
    """Bind each source role to its exact supported bounded JSON bundle interpretation."""
    if (
        table.schema_version != schema
        or table.artifact.media_type != "application/json"
        or not 0 < table.artifact.size_bytes <= MAX_SOURCE_BYTES
    ):
        raise ValueError("Source table requires its supported nonempty bounded JSON schema")


class MonthlyInput(InputBinding):
    """A long-form concept is explicit and cannot be confused with the fixed value column."""

    concept: Identifier
    value_field: Literal["value"]
    frequency: Literal["monthly"]
    period_context: Literal["instant"]
    security_id_field: Literal["security_id"]
    available_at_field: Literal["available_at"]
    period_end_field: Literal["period_end"]
    period_start_field: None
    revision_field: Literal["revision"]
    revision_policy: Literal["latest_available_then_revision_reject_conflicts"]
    history_observations: Annotated[int, Field(ge=1, le=120)]

    @model_validator(mode="after")
    def source_schema(self) -> Self:
        """Only the actual normalized monthly bundle has these literal role fields."""
        _table(self.table, "monthly-source-v1")
        return self

    def monthly_binding(self) -> MonthlyBinding:
        """Project revalidated names and semantics for the existing monthly selector."""
        value = MonthlyInput.model_validate(self)
        return MonthlyBinding(
            name=value.name,
            concept=value.concept,
            unit=value.unit,
            history_observations=value.history_observations,
            frequency="monthly",
            period_context="instant",
        )


class MonthlyUniverse(UniverseSpec):
    """Historical eligibility maps the membership collection's fixed independent clocks."""

    security_id_field: Literal["security_id"]
    included_field: Literal["included"]
    effective_at_field: Literal["effective_at"]
    available_at_field: Literal["available_at"]

    @model_validator(mode="after")
    def source_schema(self) -> Self:
        """The shared monthly source owns both normalized facts and historical membership."""
        _table(self.table, "monthly-source-v1")
        return self


class RawMarketBinding(Contract):
    """Raw quote, event and loan collections belong to one explicitly versioned market bundle."""

    table: TableReference
    quotes_field: Literal["quotes"]
    actions_field: Literal["actions"]
    borrow_grants_field: Literal["borrow_grants"]

    @model_validator(mode="after")
    def source_schema(self) -> Self:
        """A daily total-return table cannot impersonate raw marks with separate event coverage."""
        _table(self.table, "raw-market-source-v1")
        return self


class IntervalBinding(Contract):
    """Comparison series declare complete cumulative returns for exact close intervals."""

    table: TableReference
    series_id: Literal["benchmark", "risk_free"]
    rows_field: Literal["rows"]
    source_id_field: Literal["source_id"]
    series_id_field: Literal["series_id"]
    start_at_field: Literal["start_at"]
    end_at_field: Literal["end_at"]
    available_at_field: Literal["available_at"]
    value_field: Literal["cumulative_return"]
    unit: Literal["return_decimal"]
    interval: Literal["exact_cumulative_close_to_close"]

    @model_validator(mode="after")
    def source_schema(self) -> Self:
        """Annual yield or generic daily return columns cannot acquire unstated interval meaning."""
        _table(self.table, "interval-returns-v1")
        return self


class RawTiming(TimingSpec):
    """The first executor has one monthly cohort, no overlap and exactly one later open."""

    trade_delay_sessions: Annotated[int, Field(ge=1, le=1)]
    rebalance: Literal["monthly_last_session"]
    holding_months: Annotated[int, Field(ge=1, le=1)]
    vintage_allocation: Literal["nonoverlapping"]


class RawPortfolio(Contract):
    """Allocation is independent of the explicitly new post-fee funding and quantity policies."""

    allocation: AllocationSpec
    long_exposure: Annotated[int, Field(ge=1, le=1)]
    short_exposure: Annotated[int, Field(ge=1, le=1)]
    sizing_basis: Literal["post_fee_nav"]
    collateral: Literal["current_short_liability_cash_reserve_v1"]
    quantity: Literal["exact_terminating_decimal_18_v1", "whole_shares_toward_zero_v1"]
    cash_return: Literal["zero"]

    @model_validator(mode="after")
    def supported_allocation(self) -> Self:
        """Only equal-weight partitions feasible within the eight-ID capability are declared."""
        rule = self.allocation
        if (
            rule.weighting != "equal_weight"
            or rule.weight_input is not None
            or rule.bucket_count * rule.minimum_bucket_size > 8
        ):
            raise ValueError(
                "Initial raw-price capability requires a bounded equal-weight allocation"
            )
        return self


class RawPolicies(Contract):
    """Missing data and unsupported economics stop the path instead of triggering repair."""

    dataset_kind: Literal["original_fixture"]
    missing_signal: Literal["fail", "exclude_at_formation"]
    missing_price: Literal["fail"]
    unknown_terminal: Literal["fail"]
    corporate_actions: Literal["reject_any_events"]
    point_in_time: Literal["available_at_lte_formation_lt_trade"]
    freshness: Literal["explicit_requested_calendar_month_no_stale_fallback_v1"]
    short_loan: Literal["require_valid_finite_original_grant"]
    funding_failure: Literal["stop_run"]
    execution: Literal["simultaneous_exact_quote_batch"]
    fee_charge: Literal["all_absolute_trade_notional"]
    slippage: Literal["cash_charge_at_reference_quote"]
    winsorization: Literal["none"]
    standardization: Literal["none"]
    neutralization: Literal["none"]


class RawEvaluation(Contract):
    """The sample starts at its actual first formation close and ends with explicit liquidation."""

    benchmark: IntervalBinding
    risk_free: IntervalBinding
    sample_start: date
    sample_end: date
    baseline: Literal["sample_start_first_formation_close_initial_cash"]
    sample_end_policy: Literal["liquidate_at_last_session_with_costs"]
    drawdown_observations: Literal["baseline_and_session_closes"]
    metrics: Annotated[
        tuple[Literal["net_mean", "net_sharpe", "max_drawdown", "turnover"], ...],
        Field(min_length=1, max_length=4),
    ]
    annualization: Annotated[int, Field(ge=1, le=366)]

    @model_validator(mode="after")
    def complete_evaluation(self) -> Self:
        """Series selectors cannot swap roles or reference a second ignored interval bundle."""
        if self.sample_start >= self.sample_end or len(set(self.metrics)) != len(self.metrics):
            raise ValueError("Evaluation requires forward dates and unique supported metrics")
        if (
            self.benchmark.series_id != "benchmark"
            or self.risk_free.series_id != "risk_free"
            or self.benchmark.table != self.risk_free.table
        ):
            raise ValueError(
                "Comparison roles require one bound interval bundle and distinct selectors"
            )
        return self


class RawStrategySpec(Contract):
    """V3 declarations still require real bytes, calendar, funding and execution gates."""

    schema_version: Literal["factor-spec-v3"]
    profile: Literal["monthly-raw-price-post-fee-v1"]
    factor_id: Identifier
    version: Identifier
    name: Annotated[str, Field(min_length=1, max_length=200)]
    source_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1, max_length=32)]
    datasets: Annotated[tuple[DatasetLink, ...], Field(min_length=1, max_length=8)]
    signal_inputs: Annotated[tuple[MonthlyInput, ...], Field(min_length=1, max_length=32)]
    formula: Annotated[str, Field(min_length=1, max_length=2048)]
    signal_unit: Unit
    universe: MonthlyUniverse
    timing: RawTiming
    portfolio: RawPortfolio
    costs: LedgerCosts
    policies: RawPolicies
    market: RawMarketBinding
    evaluation: RawEvaluation

    def _tables(self) -> tuple[TableReference, ...]:
        """Enumerate declared roles internally while validators are constructing the model."""
        return (
            self.universe.table,
            self.market.table,
            self.evaluation.benchmark.table,
            self.evaluation.risk_free.table,
            *(binding.table for binding in self.signal_inputs),
        )

    def table_references(self) -> tuple[TableReference, ...]:
        """Return revalidated table roles without fetching or trusting source bytes."""
        return RawStrategySpec.model_validate(self)._tables()

    def _coverage(self) -> dict[str, date]:
        """Declare conservative per-dataset warmup coverage with bounded civil-month subtraction."""
        first = self.evaluation.sample_start
        result = {table.dataset_version: first for table in self._tables()}
        for binding in self.signal_inputs:
            cutoff = subtract_civil_months(first, self.timing.formation_lag_months).replace(day=1)
            months = max(binding.history_observations, self.timing.lookback_months or 0) - 1
            earliest = subtract_civil_months(cutoff, months)
            result[binding.table.dataset_version] = min(
                result[binding.table.dataset_version], earliest
            )
        return result

    def required_coverage(self) -> dict[str, date]:
        """Metadata warmup bounds never replace actual consecutive known monthly row validation."""
        return RawStrategySpec.model_validate(self)._coverage()

    def _artifacts(self) -> tuple[ArtifactRef, ...]:
        """Close source roles into one consistent bounded content-reference inventory."""
        references = (
            *self.source_refs,
            self.timing.calendar,
            *(link.manifest for link in self.datasets),
            *(table.artifact for table in self._tables()),
        )
        unique: dict[str, ArtifactRef] = {}
        for ref in references:
            if ref.sha256 in unique and ref != unique[ref.sha256]:
                raise ValueError("Repeated content hash has conflicting reference metadata")
            unique[ref.sha256] = ref
        if sum(ref.size_bytes for ref in unique.values()) > MAX_CLOSURE_BYTES:
            raise ValueError("Unique strategy artifact closure exceeds 64 MiB")
        return tuple(unique[key] for key in sorted(unique))

    def unique_artifacts(self) -> tuple[ArtifactRef, ...]:
        """Enumerate validated unique refs before admission performs any rights or byte reads."""
        return RawStrategySpec.model_validate(self)._artifacts()

    @model_validator(mode="after")
    def complete_contract(self) -> Self:
        """Bind every source, formula and supported policy without inventing v2 total returns."""
        inputs: dict[str, InputBinding] = {binding.name: binding for binding in self.signal_inputs}
        if len(inputs) != len(self.signal_inputs) or any(
            binding.table != self.universe.table for binding in self.signal_inputs
        ):
            raise ValueError("Unique formula inputs must bind the one actual monthly source")
        versions = {link.version_id for link in self.datasets}
        if len(versions) != len(self.datasets) or versions != {
            table.dataset_version for table in self._tables()
        }:
            raise ValueError("Declare exactly the unique dataset versions used by all source roles")
        if self.costs.commission_bps + self.costs.slippage_bps >= 5000:
            raise ValueError("Combined costs violate the unit-sleeve sufficient slope gate")
        if any(
            link.manifest.media_type != "application/json"
            or not 0 < link.manifest.size_bytes <= 256 * 1024
            for link in self.datasets
        ):
            raise ValueError("Dataset manifests require bounded nonempty JSON")
        calendar = self.timing.calendar
        if (
            calendar.media_type != "application/json"
            or not 0 < calendar.size_bytes <= MAX_SOURCE_BYTES
        ):
            raise ValueError("Calendar requires bounded nonempty JSON")
        self._artifacts()
        self._coverage()
        try:
            tree = parse_formula(self.formula)
        except ResearchError:
            raise ValueError("Formula is outside the supported bounded grammar") from None
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        functions = {id(call.func) for call in calls}
        names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and id(node) not in functions
        }
        if names != set(inputs):
            raise ValueError("Formula names must exactly close over declared monthly inputs")
        for call in calls:
            assert isinstance(call.func, ast.Name) and isinstance(call.args[0], ast.Name)
            if call.func.id != "compound_return":
                raise ValueError(
                    "The monthly raw-price profile cannot infer annual delta semantics"
                )
            window = call.args[1]
            assert isinstance(window, ast.Constant) and type(window.value) is int
            binding = inputs[call.args[0].id]
            if (
                binding.unit != "return_decimal"
                or binding.history_observations < window.value
                or self.timing.lookback_months is None
                or self.timing.lookback_months < window.value
            ):
                raise ValueError(
                    "Compounding requires exact monthly returns and sufficient history"
                )
        if _formula_dimensions(tree.body, inputs) != _dimensions(self.signal_unit):
            raise ValueError("Formula dimensions do not match the declared signal unit")
        return self

    @property
    def execution_sha256(self) -> str:
        """Exact execution identity retains numeric lexemes and all versioned economic choices."""
        value = RawStrategySpec.model_validate(self)
        data = value.model_dump(
            mode="json", exclude={"factor_id", "version", "name", "source_refs"}
        )
        expression = value.formula.strip()
        tree = parse_formula(expression)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                node.value = ast.get_source_segment(expression, node)
        data["formula"] = ast.dump(tree, include_attributes=False)
        data["signal_inputs"] = sorted(data["signal_inputs"], key=lambda row: row["name"])
        data["datasets"] = sorted(data["datasets"], key=lambda row: row["version_id"])
        data["evaluation"]["metrics"] = sorted(data["evaluation"]["metrics"])
        return hashlib.sha256(
            json.dumps(
                data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            ).encode()
        ).hexdigest()
