"""Explicit monthly-instant requests retain raw source identity and selected fact provenance."""

import ast
import calendar
import json
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, ValidationInfo, field_validator, model_validator

from factorforge.data.point_in_time import FundamentalFact, MembershipEvent
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.calendar import FormationPlan
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Digest, Identifier, InputName, Unit
from factorforge.domain.formula import evaluate_formula, parse_formula
from factorforge.domain.targets import CrossSection


def subtract_civil_months(day: date, months: int) -> date:
    """Bounded civil subtraction preserves the day without expanding to a later month end."""
    if type(day) is not date or type(months) is not int or not 0 <= months <= 120:
        raise ValueError("Invalid civil month cutoff")
    index = day.year * 12 + day.month - 1 - months
    if index < 12:
        raise ValueError("Civil cutoff precedes the supported date range")
    year, month_zero = divmod(index, 12)
    month = month_zero + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def revalidated_fact(row: FundamentalFact) -> FundamentalFact:
    """C4 models need explicit reconstruction so forged copies cannot bypass field validation."""
    try:
        value = FundamentalFact.model_validate(row.model_dump(), strict=True)
    except OverflowError:
        raise ValueError("Fact timestamp cannot be represented in UTC") from None
    number = value.value
    if (
        len(str(number)) > 128
        or not number.is_finite()
        or number.copy_abs() > Decimal("1e100")
        or (number and number.adjusted() < -100)
    ):
        raise ValueError("Fact numeric precision exceeds supported bounds")
    return value


def decimal_text_fact(row: object) -> FundamentalFact:
    """Parse one JSON fact only after its decimal token has been proven bounded text."""
    if (
        not isinstance(row, dict)
        or not isinstance(row.get("value"), str)
        or len(row["value"]) > 128
    ):
        raise ValueError("Fact decimal values must be bounded JSON strings")
    try:
        return FundamentalFact.model_validate_json(json.dumps(row), strict=True)
    except OverflowError:
        raise ValueError("Fact timestamp cannot be represented in UTC") from None


class MonthlySourceBundle(Contract):
    """Input-only source bytes contain no expected signals, labels, weights or outcomes."""

    schema_version: Literal["monthly-source-v1"] = "monthly-source-v1"
    facts: Annotated[tuple[FundamentalFact, ...], Field(max_length=50000)]
    membership: Annotated[tuple[MembershipEvent, ...], Field(max_length=10000)]

    @field_validator("facts", mode="before")
    @classmethod
    def decimal_wire_text(cls, rows: object, info: ValidationInfo) -> object:
        """Reject JSON numeric tokens before nested parsing can round exact source decimals."""
        if info.mode == "json" and isinstance(rows, list):
            if len(rows) > 50000:
                raise ValueError("Source facts exceed the row limit")
            return tuple(decimal_text_fact(row) for row in rows)
        return rows

    @field_validator("facts")
    @classmethod
    def validated_facts(cls, rows: tuple[FundamentalFact, ...]) -> tuple[FundamentalFact, ...]:
        """Every supplied fact is schema-valid before relevance or publication filtering."""
        return tuple(revalidated_fact(row) for row in rows)

    @field_validator("membership")
    @classmethod
    def validated_membership(cls, rows: tuple[MembershipEvent, ...]) -> tuple[MembershipEvent, ...]:
        """Historical membership models also require reconstruction rather than instance trust."""
        try:
            return tuple(
                MembershipEvent.model_validate(row.model_dump(), strict=True) for row in rows
            )
        except OverflowError:
            raise ValueError("Membership timestamp cannot be represented in UTC") from None


class MonthlyBinding(Contract):
    """A normalized concept mapping is explicit; no wide-table field name is reinterpreted."""

    name: InputName
    concept: Identifier
    unit: Unit
    history_observations: Annotated[int, Field(ge=1, le=120)]
    frequency: Literal["monthly"]
    period_context: Literal["instant"]


class MonthlySignalRequest(Contract):
    """The request hashes calendar, exact concept mappings, period lag and closed formula."""

    schema_version: Literal["monthly-signal-request-v1"] = "monthly-signal-request-v1"
    formation: FormationPlan
    formula: Annotated[str, Field(min_length=1, max_length=2048)]
    formation_lag_months: Annotated[int, Field(ge=0, le=120)]
    bindings: Annotated[tuple[MonthlyBinding, ...], Field(min_length=1, max_length=32)]
    capitalization_binding: MonthlyBinding | None
    freshness: Literal["explicit_requested_calendar_month_no_stale_fallback_v1"]
    revision_policy: Literal["latest_available_then_revision_reject_conflicts"]

    def all_bindings(self) -> tuple[MonthlyBinding, ...]:
        """Return the exact formula inventory plus an explicitly requested weight input."""
        return self.bindings + (
            (self.capitalization_binding,) if self.capitalization_binding else ()
        )

    def economic_cutoff(self) -> date:
        """Derive the one publication-independent economic cutoff bound by this request."""
        return subtract_civil_months(self.formation.formation_at.date(), self.formation_lag_months)

    def requested_periods(self) -> dict[str, tuple[date, ...]]:
        """Each binding requests consecutive civil months, oldest first, without stale fallback."""
        cutoff = self.economic_cutoff().replace(day=1)
        return {
            binding.name: tuple(
                subtract_civil_months(cutoff, lag)
                for lag in reversed(range(binding.history_observations))
            )
            for binding in self.all_bindings()
        }

    @model_validator(mode="after")
    def closed_monthly_formula(self) -> Self:
        """Monthly compounding requires return units and complete history, without annual deltas."""
        self.requested_periods()
        bindings = {binding.name: binding for binding in self.bindings}
        if len({binding.name for binding in self.all_bindings()}) != len(self.all_bindings()):
            raise ValueError("Monthly binding names must be unique")
        if self.capitalization_binding and self.capitalization_binding.unit != "USD":
            raise ValueError("Capitalization requires explicit USD units")
        try:
            tree = parse_formula(self.formula)
        except ResearchError:
            raise ValueError("Monthly formula uses unsupported syntax") from None
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        function_nodes = {id(call.func) for call in calls}
        names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and id(node) not in function_nodes
        }
        if names != set(bindings):
            raise ValueError("Formula names must match the declared monthly bindings")
        for call in calls:
            assert isinstance(call.func, ast.Name) and isinstance(call.args[0], ast.Name)
            if call.func.id != "compound_return":
                raise ValueError("Annual delta requires a separately declared fiscal-period policy")
            window = call.args[1]
            assert isinstance(window, ast.Constant) and type(window.value) is int
            binding = bindings[call.args[0].id]
            if binding.unit != "return_decimal" or binding.history_observations < window.value:
                raise ValueError(
                    "Monthly compounding requires decimal returns and sufficient history"
                )
        return self


class MonthlySelection(Contract):
    """A selected natural fact context is retained alongside its requested calendar month."""

    binding_name: InputName
    requested_month: date
    fact: FundamentalFact

    @field_validator("fact", mode="before")
    @classmethod
    def decimal_wire_text(cls, row: object, info: ValidationInfo) -> object:
        """Saved provenance preserves the same decimal text wire contract as the source bundle."""
        return decimal_text_fact(row) if info.mode == "json" else row

    @field_validator("fact")
    @classmethod
    def fresh_fact(cls, row: FundamentalFact) -> FundamentalFact:
        """Selected provenance cannot contain an unvalidated C4 model copy."""
        return revalidated_fact(row)


class MissingMonthlyObservation(Contract):
    """Missing required calendar months are explicit and never filled from stale revisions."""

    binding_name: InputName
    security_id: Identifier
    requested_month: date


class MonthlyAssembly(Contract):
    """A receipt binds actual source bytes, the request and complete selected/missing provenance."""

    schema_version: Literal["monthly-assembly-v1"] = "monthly-assembly-v1"
    request: MonthlySignalRequest
    request_sha256: Digest
    source_ref: ArtifactRef
    economic_cutoff: date
    cross_section: CrossSection
    selections: Annotated[tuple[MonthlySelection, ...], Field(max_length=100000)]
    missing: Annotated[tuple[MissingMonthlyObservation, ...], Field(max_length=100000)]

    @model_validator(mode="after")
    def coherent_lineage(self) -> Self:
        """Saved receipts retain one inventory and cannot relabel source/request identities."""
        if (
            self.request_sha256 != self.request.sha256
            or self.cross_section.formation != self.request.formation
        ):
            raise ValueError("Assembly request identity or formation does not match")
        if self.cross_section.source_refs != (self.source_ref,):
            raise ValueError("Assembly source reference does not match the cross-section")
        if self.economic_cutoff != self.request.economic_cutoff():
            raise ValueError("Assembly economic cutoff differs from the request")
        if (
            tuple(row.security_id for row in self.cross_section.observations)
            != self.cross_section.universe
        ):
            raise ValueError("Every historical eligible identity must retain an observation")
        keys = [
            (row.binding_name, row.fact.security_id, row.requested_month) for row in self.selections
        ]
        keys += [(row.binding_name, row.security_id, row.requested_month) for row in self.missing]
        if len(keys) > 100000 or len(set(keys)) != len(keys):
            raise ValueError("Requested monthly cells must be unique and bounded")
        bindings = {binding.name: binding for binding in self.request.all_bindings()}
        universe = set(self.cross_section.universe)
        periods = self.request.requested_periods()
        if len(universe) * sum(len(months) for months in periods.values()) > 100000:
            raise ValueError("Requested monthly cells exceed the receipt budget")
        expected = {
            (name, security, month)
            for name, months in periods.items()
            for security in universe
            for month in months
        }
        if set(keys) != expected:
            raise ValueError("Receipt must retain every requested monthly cell")
        for row in self.selections:
            binding = bindings[row.binding_name]
            if (
                row.fact.concept != binding.concept
                or row.fact.unit != binding.unit
                or row.fact.period_start is not None
                or row.fact.period_end > self.economic_cutoff
                or row.fact.period_end.replace(day=1) != row.requested_month
                or row.fact.available_at > self.request.formation.formation_at
            ):
                raise ValueError(
                    "Selected provenance violates its declared period or publication cutoff"
                )
            if binding.unit == "return_decimal" and row.fact.value < -1:
                raise ValueError("Selected simple monthly return cannot be below minus one")
            if self.request.capitalization_binding == binding and row.fact.value <= 0:
                raise ValueError("Selected capitalization must be positive")
        return self

    @model_validator(mode="after")
    def coherent_values(self) -> Self:
        """Saved scalars must equal the complete selected histories rather than arbitrary labels."""
        selected = {
            (row.binding_name, row.fact.security_id, row.requested_month): row.fact.value
            for row in self.selections
        }
        periods = self.request.requested_periods()
        for observation in self.cross_section.observations:
            histories = {}
            for name, months in periods.items():
                keys = [(name, observation.security_id, month) for month in months]
                if all(key in selected for key in keys):
                    histories[name] = tuple(selected[key] for key in keys)
            signal = None
            if all(binding.name in histories for binding in self.request.bindings):
                try:
                    signal = evaluate_formula(
                        self.request.formula,
                        scalars={
                            binding.name: histories[binding.name][-1]
                            for binding in self.request.bindings
                        },
                        series={
                            binding.name: histories[binding.name]
                            for binding in self.request.bindings
                        },
                    )
                except ResearchError:
                    raise ValueError("Selected history cannot produce a valid scalar") from None
            actual = Decimal(observation.signal) if observation.signal is not None else None
            if actual != signal:
                raise ValueError("Saved signal differs from selected monthly histories")
            cap = self.request.capitalization_binding
            expected_cap = histories[cap.name][-1] if cap and cap.name in histories else None
            actual_cap = (
                Decimal(observation.capitalization)
                if observation.capitalization is not None
                else None
            )
            if actual_cap != expected_cap:
                raise ValueError("Saved capitalization differs from selected monthly history")
        return self
