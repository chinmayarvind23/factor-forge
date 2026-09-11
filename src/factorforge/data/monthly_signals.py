"""Bounded monthly source assembly verifies raw bytes before point-in-time interpretation."""

import json
from datetime import date
from decimal import Decimal

from pydantic import ValidationError

from factorforge.data.artifacts import ArtifactStore, verify_bytes
from factorforge.data.point_in_time import FundamentalFact, select_facts, select_universe
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.formula import evaluate_formula
from factorforge.domain.monthly_signals import (
    MissingMonthlyObservation,
    MonthlyAssembly,
    MonthlySelection,
    MonthlySignalRequest,
    MonthlySourceBundle,
    subtract_civil_months,
)
from factorforge.domain.targets import CrossSection, SignalValue

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_REQUESTED_CELLS = 100000


def _failure(code: str) -> ResearchError:
    """Typed failures report scope without exposing raw source values or host paths."""
    return ResearchError(code, "Monthly source assembly cannot produce a valid cross-section.", 422)


def civil_month_cutoff(day: date, months: int) -> date:
    """Subtract civil months while preserving the day and clamping only to a shorter month."""
    try:
        return subtract_civil_months(day, months)
    except ValueError:
        raise _failure("MONTHLY_REQUEST_INVALID") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """No duplicate JSON member can be silently replaced before model validation."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate source member")
        result[key] = value
    return result


def _nonfinite(token: str) -> object:
    """JSON's optional nonfinite extensions are not valid source data."""
    raise ValueError("Nonfinite source value")


def _source(ref: ArtifactRef, store: ArtifactStore) -> MonthlySourceBundle:
    """Hash verification and bounded strict parsing precede all source record interpretation."""
    if ref.size_bytes > MAX_SOURCE_BYTES or ref.media_type != "application/json":
        raise _failure("MONTHLY_SOURCE_LIMIT")
    try:
        raw = store.get(ArtifactRef.model_validate(ref).model_copy())
    except ResearchError:
        raise
    except Exception:
        raise _failure("MONTHLY_SOURCE_UNAVAILABLE") from None
    if type(raw) is not bytes:
        raise _failure("MONTHLY_SOURCE_INVALID")
    verify_bytes(raw, ref)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
        pending = [(value, 0)]
        while pending:
            node, depth = pending.pop()
            if depth > 16:
                raise ValueError("Source JSON exceeds its nesting bound")
            if isinstance(node, dict):
                pending.extend((child, depth + 1) for child in node.values())
            elif isinstance(node, list):
                pending.extend((child, depth + 1) for child in node)
        return MonthlySourceBundle.model_validate_json(raw, strict=True)
    except (ValueError, ValidationError, OverflowError, RecursionError):
        raise _failure("MONTHLY_SOURCE_INVALID") from None


def load_monthly(ref: ArtifactRef, store: ArtifactStore) -> MonthlySourceBundle:
    """Expose the verified source loader without treating successful parsing as signal selection."""
    try:
        ref = ArtifactRef.model_validate(ref)
    except ValueError:
        raise _failure("MONTHLY_SOURCE_INVALID") from None
    return _source(ref, store)


def _selected_index(
    source: MonthlySourceBundle,
    request: MonthlySignalRequest,
    cutoff: date,
) -> dict[tuple[str, str, str, date], tuple[FundamentalFact, ...]]:
    """Validate relevant known history once and index economic months without repeated scans."""
    contexts = {(binding.concept, binding.unit) for binding in request.all_bindings()}
    relevant = tuple(
        row
        for row in source.facts
        if row.period_start is None and (row.concept, row.unit) in contexts
    )
    selected = select_facts(relevant, request.formation.formation_at, request.formation.trade_at)
    index: dict[tuple[str, str, str, date], list[FundamentalFact]] = {}
    for row in selected:
        if row.period_end <= cutoff:
            key = (row.security_id, row.concept, row.unit, row.period_end.replace(day=1))
            index.setdefault(key, []).append(row)
    return {key: tuple(rows) for key, rows in index.items()}


def _assemble(
    ref: ArtifactRef,
    source: MonthlySourceBundle,
    request: MonthlySignalRequest,
) -> MonthlyAssembly:
    """Build at most the preflighted number of requested cells using one natural-context index."""
    cutoff = request.economic_cutoff()
    universe = select_universe(
        source.membership, request.formation.formation_at, request.formation.trade_at
    )
    if not universe:
        raise _failure("MONTHLY_EMPTY_UNIVERSE")
    bindings = request.all_bindings()
    if (
        len(universe) * sum(binding.history_observations for binding in bindings)
        > MAX_REQUESTED_CELLS
    ):
        raise _failure("MONTHLY_WORK_LIMIT")
    periods = request.requested_periods()
    indexed = _selected_index(source, request, cutoff)
    observations = []
    selections = []
    missing = []
    for security in universe:
        values: dict[str, tuple[Decimal, ...]] = {}
        for binding in bindings:
            history = []
            for month in periods[binding.name]:
                rows = indexed.get((security, binding.concept, binding.unit, month), ())
                if len(rows) > 1:
                    raise _failure("MONTHLY_PERIOD_AMBIGUOUS")
                if not rows:
                    missing.append(
                        MissingMonthlyObservation(
                            binding_name=binding.name, security_id=security, requested_month=month
                        )
                    )
                else:
                    fact = rows[0]
                    if binding.unit == "return_decimal" and fact.value < -1:
                        raise _failure("MONTHLY_RETURN_INVALID")
                    if request.capitalization_binding == binding and fact.value <= 0:
                        raise _failure("MONTHLY_CAPITALIZATION_INVALID")
                    history.append(fact.value)
                    selections.append(
                        MonthlySelection(
                            binding_name=binding.name, requested_month=month, fact=fact
                        )
                    )
            if len(history) == binding.history_observations:
                values[binding.name] = tuple(history)
        signal = None
        if all(binding.name in values for binding in request.bindings):
            signal = str(
                evaluate_formula(
                    request.formula,
                    scalars={
                        binding.name: values[binding.name][-1] for binding in request.bindings
                    },
                    series={binding.name: values[binding.name] for binding in request.bindings},
                )
            )
        cap_binding = request.capitalization_binding
        cap = (
            str(values[cap_binding.name][-1])
            if cap_binding and cap_binding.name in values
            else None
        )
        observations.append(SignalValue(security_id=security, signal=signal, capitalization=cap))
    return MonthlyAssembly(
        request=request,
        request_sha256=request.sha256,
        source_ref=ref,
        economic_cutoff=cutoff,
        cross_section=CrossSection(
            source_refs=(ref,),
            formation=request.formation,
            universe=universe,
            observations=tuple(observations),
        ),
        selections=tuple(selections),
        missing=tuple(missing),
    )


def assemble_monthly_signals(
    source_ref: ArtifactRef,
    store: ArtifactStore,
    request: MonthlySignalRequest,
) -> MonthlyAssembly:
    """Assemble monthly-instant inputs without inferring annual, funding or execution rules."""
    try:
        reference = ArtifactRef.model_validate(source_ref)
        validated = MonthlySignalRequest.model_validate(request)
    except (ValueError, ValidationError, OverflowError):
        raise _failure("MONTHLY_REQUEST_INVALID") from None
    source = _source(reference, store)
    try:
        return _assemble(reference, source, validated)
    except (ValueError, ValidationError, OverflowError):
        raise _failure("MONTHLY_ASSEMBLY_INVALID") from None
