"""Complete research contracts keep source uncertainty outside executable factor specifications."""

import ast
import hashlib
import json
from datetime import date, timedelta
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.formula import parse_formula

type Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
type InputName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
type Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
type Unit = Literal["USD", "shares", "USD_per_share", "return_decimal", "dimensionless"]
type PositiveMonths = Annotated[int, Field(ge=1, le=120)]


class Contract(BaseModel):
    """Immutable tuple-based contracts have stable identities and revalidate copied nested
    models."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )

    @field_validator("*")
    @classmethod
    def portable_text(cls, value: object) -> object:
        """Single-line metadata cannot hide blank labels or control-bearing execution choices."""
        if isinstance(value, str) and (not value.strip() or not value.isprintable()):
            raise ValueError("Contract text must be nonblank and printable")
        return value

    def canonical_bytes(self) -> bytes:
        """Canonical JSON binds declared choices without depending on formatting or host paths."""
        validated = type(self).model_validate(self)
        return json.dumps(
            validated.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    @property
    def sha256(self) -> str:
        """Changing a declared choice produces a new immutable contract identity."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class DatasetLink(Contract):
    """The canonical manifest bytes themselves determine the catalog dataset version."""

    version_id: Digest
    manifest: ArtifactRef

    @model_validator(mode="after")
    def manifest_identity(self) -> Self:
        """A separate version label cannot point at different manifest bytes."""
        if self.manifest.sha256 != self.version_id or self.manifest.size_bytes > 256 * 1024:
            raise ValueError("Dataset link must identify a bounded canonical manifest")
        return self


class TableReference(Contract):
    """A logical table binds schema interpretation and exact bytes within one dataset version."""

    dataset_version: Digest
    object_name: Identifier
    schema_version: Identifier
    artifact: ArtifactRef


class InputBinding(Contract):
    """Exact columns, units and publication fields prevent implicit conversions or timing
    guesses."""

    name: InputName
    table: TableReference
    value_field: InputName
    unit: Unit
    frequency: Literal["daily", "monthly", "annual"]
    period_context: Literal["instant", "duration"]
    security_id_field: InputName
    available_at_field: InputName
    period_end_field: InputName
    period_start_field: InputName | None
    revision_field: InputName | None
    revision_policy: Literal[
        "latest_available_then_revision_reject_conflicts", "unique_known_fact_reject_conflicts"
    ]
    history_observations: Annotated[int, Field(ge=1, le=1200)]

    @model_validator(mode="after")
    def explicit_context(self) -> Self:
        """Duration facts retain their start; availability must not alias an economic period."""
        if (self.period_context == "duration") != (self.period_start_field is not None):
            raise ValueError("Duration context requires an explicit start field")
        names = [
            self.value_field,
            self.security_id_field,
            self.available_at_field,
            self.period_end_field,
            *([self.period_start_field] if self.period_start_field else []),
            *([self.revision_field] if self.revision_field else []),
        ]
        if len(set(names)) != len(names):
            raise ValueError("Value, identity, availability and period fields must be distinct")
        if (self.revision_field is not None) != (
            self.revision_policy == "latest_available_then_revision_reject_conflicts"
        ):
            raise ValueError("Revision policy must match the declared revision field")
        return self


class UniverseSpec(Contract):
    """The initial universe uses historical known/effective events and permanent security IDs."""

    table: TableReference
    security_id_namespace: Identifier
    security_id_field: InputName
    included_field: InputName
    effective_at_field: InputName
    available_at_field: InputName
    policy: Literal["known_effective_events"]
    eligibility: Literal["historical_membership_only"]

    @model_validator(mode="after")
    def independent_roles(self) -> Self:
        """Known-at and effective-at clocks cannot alias each other or membership/identity
        fields."""
        roles = (
            self.security_id_field,
            self.included_field,
            self.effective_at_field,
            self.available_at_field,
        )
        if len(set(roles)) != len(roles):
            raise ValueError("Universe field roles must be distinct")
        return self


class TimingSpec(Contract):
    """Calendar bytes and explicit cohort timing remain distinct from data publication time."""

    calendar: ArtifactRef
    calendar_id: Identifier
    timezone: Literal["UTC"]
    formation: Literal["session_close"]
    trade: Literal["subsequent_session_open"]
    trade_delay_sessions: Annotated[int, Field(ge=1, le=20)]
    rebalance: Literal["monthly_last_session", "annual_june_last_session"]
    lookback_months: PositiveMonths | None
    formation_lag_months: Annotated[int, Field(ge=0, le=120)]
    holding_months: PositiveMonths
    vintage_allocation: Literal["nonoverlapping", "equal_weight_active"]
    within_cohort: Literal["buy_and_hold"]

    @model_validator(mode="after")
    def explicit_vintages(self) -> Self:
        """Overlapping holding cohorts cannot silently be replaced by one reconstituted
        portfolio."""
        interval = 1 if self.rebalance == "monthly_last_session" else 12
        overlapping = self.holding_months > interval
        if overlapping != (self.vintage_allocation == "equal_weight_active"):
            raise ValueError("Vintage allocation must match the declared holding overlap")
        if self.holding_months % interval:
            raise ValueError("This contract requires holdings aligned with formation intervals")
        return self


class PortfolioSpec(Contract):
    """The first long-short contract fixes gross exposures and records every weighting
    convention."""

    direction: Literal["long_high_short_low", "long_low_short_high"]
    bucket_count: Annotated[int, Field(ge=2, le=100)]
    weighting: Literal["equal_weight", "value_weight"]
    weight_input: InputName | None
    breakpoints: Literal["all_eligible"]
    ties: Literal["stable_security_id"]
    minimum_bucket_size: Annotated[int, Field(ge=1, le=1000)]
    long_exposure: Annotated[int, Field(ge=1, le=1)]
    short_exposure: Annotated[int, Field(ge=1, le=1)]
    short_proceeds: Literal["segregated"]
    cash_return: Literal["zero"]

    @model_validator(mode="after")
    def explicit_weight_input(self) -> Self:
        """Value weights require declared capitalization data; equal weights cannot hide an
        input."""
        if (self.weighting == "value_weight") != (self.weight_input is not None):
            raise ValueError("Weighting input does not match weighting convention")
        return self


class CostSpec(Contract):
    """Whole basis-point costs are explicit, including any intentionally zero financing costs."""

    commission_bps: Annotated[int, Field(ge=0, le=10000)]
    slippage_bps: Annotated[int, Field(ge=0, le=10000)]
    borrow_bps_annual: Annotated[int, Field(ge=0, le=10000)]
    financing_bps_annual: Annotated[int, Field(ge=0, le=10000)]
    turnover: Literal["absolute_change_from_drifted_weights"]
    charge: Literal["all_trades"]
    day_count: Literal["actual_365"]


class DataPolicies(Contract):
    """Unknown returns/exits stop accounting; no implicit repair or signal transform is
    supported."""

    missing_signal: Literal["exclude_at_formation", "fail"]
    missing_return: Literal["fail"]
    unknown_terminal: Literal["fail"]
    corporate_actions: Literal["total_return_includes_actions_and_delisting"]
    point_in_time: Literal["available_at_lte_formation_lt_trade"]
    winsorization: Literal["none"]
    standardization: Literal["none"]
    neutralization: Literal["none"]


class EvaluationSpec(Contract):
    """Return comparison, annualization and statistical lag choices are predeclared inputs."""

    benchmark: InputBinding
    risk_free: InputBinding
    sample_start: date
    sample_end: date
    sample_end_policy: Literal["liquidate_at_last_session_with_costs"]
    metrics: Annotated[
        tuple[Literal["net_mean", "net_sharpe", "hac_tstat", "max_drawdown", "turnover"], ...],
        Field(min_length=1, max_length=5),
    ]
    annualization: Annotated[int, Field(ge=1, le=366)]
    hac_lags: Annotated[int, Field(ge=0, le=252)]
    seeds: Annotated[
        tuple[Annotated[int, Field(ge=0, le=2**32 - 1)], ...], Field(min_length=1, max_length=16)
    ]

    @model_validator(mode="after")
    def explicit_evaluation(self) -> Self:
        """Metric/seed multiplicity is visible and comparison series use daily decimal returns."""
        if len(set(self.metrics)) != len(self.metrics) or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("Metrics and seeds must be unique")
        if self.sample_start > self.sample_end:
            raise ValueError("Evaluation sample dates must be ordered")
        if any(
            value.unit != "return_decimal" or value.frequency != "daily"
            for value in (self.benchmark, self.risk_free)
        ):
            raise ValueError("Comparison inputs require daily decimal returns")
        return self


def _dimensions(unit: Unit) -> dict[str, int]:
    """Decimal returns are dimensionless arithmetic but retain semantic units in input contracts."""
    return (
        {"USD": 1, "shares": -1}
        if unit == "USD_per_share"
        else {unit: 1}
        if unit in {"USD", "shares"}
        else {}
    )


def _formula_dimensions(node: ast.expr, inputs: dict[str, InputBinding]) -> dict[str, int]:
    """The already allowlisted AST is inspected for units without executing research arithmetic."""
    if isinstance(node, ast.Constant):
        return {}
    if isinstance(node, ast.Name):
        return _dimensions(inputs[node.id].unit)
    if isinstance(node, ast.UnaryOp):
        return _formula_dimensions(node.operand, inputs)
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name) and isinstance(node.args[0], ast.Name)
        return (
            {} if node.func.id == "compound_return" else _dimensions(inputs[node.args[0].id].unit)
        )
    assert isinstance(node, ast.BinOp)
    left, right = _formula_dimensions(node.left, inputs), _formula_dimensions(node.right, inputs)
    if isinstance(node.op, (ast.Add, ast.Sub)):
        if left != right:
            raise ValueError("Addition/subtraction require equal units")
        return left
    result = dict(left)
    sign = -1 if isinstance(node.op, ast.Div) else 1
    for unit, power in right.items():
        result[unit] = result.get(unit, 0) + sign * power
    return {unit: power for unit, power in result.items() if power}


class FactorSpec(Contract):
    """A complete declared specification is still subject to data-row, engine and sandbox gates."""

    schema_version: Literal["factor-spec-v1"] = "factor-spec-v1"
    factor_id: Identifier
    version: Identifier
    name: Annotated[str, Field(min_length=1, max_length=200)]
    source_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1, max_length=32)]
    datasets: Annotated[tuple[DatasetLink, ...], Field(min_length=1, max_length=8)]
    signal_inputs: Annotated[tuple[InputBinding, ...], Field(min_length=1, max_length=32)]
    formula: Annotated[str, Field(min_length=1, max_length=2048)]
    signal_unit: Unit
    universe: UniverseSpec
    timing: TimingSpec
    portfolio: PortfolioSpec
    costs: CostSpec
    policies: DataPolicies
    returns: InputBinding
    evaluation: EvaluationSpec

    def table_references(self) -> tuple[TableReference, ...]:
        """Enumerate every data role for manifest and byte verification before experiment
        planning."""
        return (
            self.universe.table,
            self.returns.table,
            self.evaluation.benchmark.table,
            self.evaluation.risk_free.table,
            *(value.table for value in self.signal_inputs),
        )

    def required_coverage(self) -> dict[str, date]:
        """Per-role warmup bounds screen metadata; actual observation counts still need row
        validation."""
        start = self.evaluation.sample_start
        required = {table.dataset_version: start for table in self.table_references()}
        for binding in self.signal_inputs:
            if binding.frequency == "annual":
                history_months = 12 * binding.history_observations
                if binding.period_context == "duration":
                    history_months += 12
            elif binding.frequency == "monthly":
                history_months = binding.history_observations
            else:
                history_months = 0
            months = self.timing.formation_lag_months + max(
                self.timing.lookback_months or 0, history_months
            )
            month_index = start.year * 12 + start.month - 1 - months
            if month_index < 12:
                raise ValueError("Required history precedes the supported calendar")
            earliest = date(month_index // 12, month_index % 12 + 1, 1)
            if binding.frequency == "daily":
                try:
                    earliest -= timedelta(days=binding.history_observations)
                except OverflowError:
                    raise ValueError(
                        "Required daily history precedes the supported calendar"
                    ) from None
            required[binding.table.dataset_version] = min(
                required[binding.table.dataset_version], earliest
            )
        return required

    @model_validator(mode="after")
    def complete_contract(self) -> Self:
        """Close formula names, temporal operators, dataset links and dimensional interpretation."""
        self.required_coverage()
        inputs = {value.name: value for value in self.signal_inputs}
        if len(inputs) != len(self.signal_inputs):
            raise ValueError("Signal input names must be unique")
        versions = {link.version_id for link in self.datasets}
        if len(versions) != len(self.datasets):
            raise ValueError("Dataset versions must be unique")
        if {table.dataset_version for table in self.table_references()} != versions:
            raise ValueError("Declare exactly the datasets used by table references")
        if self.returns.unit != "return_decimal" or self.returns.frequency != "daily":
            raise ValueError("Accounting requires daily decimal total returns")
        try:
            tree = parse_formula(self.formula)
        except ResearchError:
            raise ValueError("Factor formula is outside the supported grammar") from None
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        call_functions = {id(node.func) for node in calls}
        names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and id(node) not in call_functions
        }
        weight = self.portfolio.weight_input
        if names | ({weight} if weight else set()) != set(inputs):
            raise ValueError("Declare exactly formula and weighting inputs")
        if weight and inputs[weight].unit != "USD":
            raise ValueError("Value-weight input requires exact USD capitalization")
        for call in calls:
            assert isinstance(call.func, ast.Name) and isinstance(call.args[0], ast.Name)
            binding = inputs[call.args[0].id]
            if call.func.id == "delta":
                if binding.frequency != "annual" or binding.history_observations < 2:
                    raise ValueError("Delta requires two annual observations")
            else:
                window = call.args[1]
                assert isinstance(window, ast.Constant) and type(window.value) is int
                if (
                    binding.frequency != "monthly"
                    or binding.unit != "return_decimal"
                    or binding.history_observations < window.value
                    or self.timing.lookback_months is None
                    or self.timing.lookback_months < window.value
                ):
                    raise ValueError(
                        "Compounding requires an explicit sufficient monthly return window"
                    )
        if _formula_dimensions(tree.body, inputs) != _dimensions(self.signal_unit):
            raise ValueError("Formula dimensions do not match declared signal units")
        return self

    @property
    def execution_sha256(self) -> str:
        """Exact execution dedup ignores candidate labels/evidence while retaining all research
        choices."""
        validated = FactorSpec.model_validate(self)
        value = validated.model_dump(
            mode="json", exclude={"factor_id", "version", "name", "source_refs"}
        )
        expression = validated.formula.strip()
        tree = parse_formula(expression)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                # This private fingerprint tree is never evaluated; retain exact numeric lexemes.
                node.value = ast.get_source_segment(expression, node)
        value["formula"] = ast.dump(tree, include_attributes=False)
        value["signal_inputs"] = sorted(value["signal_inputs"], key=lambda item: item["name"])
        value["datasets"] = sorted(value["datasets"], key=lambda item: item["version_id"])
        return hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            ).encode()
        ).hexdigest()
