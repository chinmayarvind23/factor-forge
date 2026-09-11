"""Hand-authored examples test a critical-field pilot without disclosing source-paper gold."""

from decimal import Decimal
from typing import cast

import pytest
from pydantic import ValidationError

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.extraction import SourceExtraction
from factorforge.evaluation.extraction import (
    CaseGrade,
    CriticalFieldReport,
    GoldCase,
    NumericalVector,
    Outcome,
    grade_extraction,
    score_extractions,
)
from factorforge.retrieval.extraction import ExtractionResult


def observation(**updates: object) -> SourceExtraction:
    """A fictional ratio strategy keeps public tests independent of private paper selections."""
    values: dict[str, object] = {
        "status": "extracted",
        "refusal_reason": None,
        "refusal_category": None,
        "formula": "(sales-cost)/assets",
        "required_inputs": ["sales", "cost", "assets"],
        "long_short_direction": "long_high_short_low",
        "bucket_count": 4,
        "weighting": "equal_weight",
        "lookback_months": None,
        "holding_months": 3,
        "rebalance_frequency": "quarterly",
        "formation_lag_months": 0,
        "formation_rule": "Use the known report at formation.",
        "source_pages": [2],
    }
    values.update(updates)
    return SourceExtraction.model_validate(values)


def gold(case_id: str = "ratio") -> GoldCase:
    """Three distinct signed examples expose sign, denominator and constant substitutions."""
    vectors = tuple(
        NumericalVector(
            name=f"example-{index}",
            scalars={"sales": sales, "cost": cost, "assets": assets},
            expected=answer,
        )
        for index, (sales, cost, assets, answer) in enumerate(
            [("90", "30", "120", "0.5"), ("40", "70", "150", "-0.2"), ("80", "20", "240", "0.25")]
        )
    )
    return GoldCase(
        case_id=case_id,
        paper_id="fictional",
        source_sha256="a" * 64,
        expected=observation(),
        numerical_vectors=vectors,
        allowed_source_pages=(2, 3),
    )


def result(status: str, value: SourceExtraction | None) -> ExtractionResult:
    """Outcome evidence identity is a placeholder; the service owns artifact authentication."""
    return ExtractionResult.model_validate(
        {
            "status": status,
            "observation": value,
            "record": ArtifactRef(sha256="b" * 64, size_bytes=1, media_type="application/json"),
        }
    )


def test_equivalent_formula_and_input_order_pass_all_nine_fields() -> None:
    """Arithmetic fixtures allow rearrangement while archived prose is outside machine grading."""
    actual = observation(
        formula="sales/assets-cost/assets",
        required_inputs=["assets", "cost", "sales"],
        formation_rule="Different wording.",
    )
    grade = grade_extraction(actual, gold(), "extracted")
    assert grade.matched_fields == 9
    assert grade.all_critical_fields_match
    assert grade.formation_rule_observed == "Different wording."
    assert grade.gold_sha256 == gold().sha256


def test_every_failed_attempt_stays_in_denominator() -> None:
    """Refused, malformed, unavailable and admission failures cannot disappear from accuracy."""
    statuses = ("extracted", "refused", "invalid", "provider_failed", "input_rejected")
    cases = tuple(gold(status) for status in statuses)
    attempts = {
        status: result(status, observation() if status == "extracted" else None)
        for status in statuses
    }
    report = score_extractions(cases, attempts)
    assert report.name == "critical_field_pilot"
    assert report.attempted_cases == 5
    assert report.matched_fields == 9
    assert report.total_fields == 45
    assert report.critical_field_accuracy == 0.2
    assert report.all_fields_case_accuracy == 0.2


@pytest.mark.parametrize(
    "expression", ["-(sales-cost)/assets", "(sales-cost)/sales", "0.5", "abs(sales)"]
)
def test_wrong_formulas_fail_without_repair(expression: str) -> None:
    """A single formula failure affects its named field and is never silently rewritten."""
    grade = grade_extraction(observation(formula=expression), gold(), "extracted")
    assert not grade.field_matches["formula"]
    assert grade.matched_fields == 8


def test_null_and_known_zero_are_distinct() -> None:
    """Nullable timing fields retain source uncertainty instead of becoming a default zero."""
    grade = grade_extraction(observation(formation_lag_months=None), gold(), "extracted")
    assert not grade.field_matches["formation_lag_months"]
    assert grade.field_matches["lookback_months"]


def test_gold_revalidates_mutated_nested_vectors_and_expected_values() -> None:
    """Frozen outer models cannot authenticate subsequently mutated nested dictionaries or lists."""
    case = gold()
    case.numerical_vectors[0].scalars["assets"] = "0"
    with pytest.raises(ResearchError, match="gold"):
        grade_extraction(observation(), case, "extracted")
    case = gold()
    case.expected.required_inputs.append("unexpected")
    with pytest.raises(ResearchError):
        grade_extraction(observation(), case, "extracted")


def test_vector_rejects_nonfinite_and_keeps_full_series() -> None:
    """Series remain oldest-to-newest with no destructive truncation during validation."""
    values = ("0.8", "0.25", "-0.2", "0")
    vector = NumericalVector(name="history", series={"returns": values}, expected="0")
    assert vector.series["returns"] == values
    with pytest.raises(ValidationError):
        NumericalVector(name="bad", scalars={"value": "NaN"}, expected="0")
    with pytest.raises(ValidationError):
        NumericalVector(name="bad", expected="Infinity")


def test_case_inventory_and_empty_pilot_are_invalid() -> None:
    """The caller cannot inflate performance by silently dropping frozen attempted cases."""
    for cases, attempts in (((), {}), ((gold(),), {}), ((gold(), gold()), {})):
        with pytest.raises(ResearchError):
            score_extractions(cases, attempts)


def test_canonical_hash_binds_vectors_and_gold_fields() -> None:
    """Canonical bytes survive JSON transport and include the full numerical input arrays."""
    case = gold()
    assert GoldCase.model_validate_json(case.canonical_bytes()).sha256 == case.sha256
    assert len(case.sha256) == 64
    assert Decimal(case.numerical_vectors[0].expected) == Decimal("0.5")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required_inputs", ["sales", "assets"]),
        ("long_short_direction", "long_low_short_high"),
        ("bucket_count", 5),
        ("weighting", "value_weight"),
        ("lookback_months", 1),
        ("holding_months", 6),
        ("rebalance_frequency", "monthly"),
        ("formation_lag_months", None),
    ],
)
def test_each_structural_field_requires_exact_equality(field: str, value: object) -> None:
    """Each source quantity has an independent named decision, including required input sets."""
    grade = grade_extraction(observation(**{field: value}), gold(), "extracted")
    assert not grade.field_matches[field]
    assert grade.matched_fields == (7 if field == "required_inputs" else 8)


@pytest.mark.parametrize("status", ["refused", "invalid", "provider_failed", "input_rejected"])
def test_nonextracted_outcome_cannot_claim_valid_observation_credit(status: str) -> None:
    """A contradictory service status fails closed even when its observation looks correct."""
    report = score_extractions((gold(),), {"ratio": result(status, observation())})
    assert report.matched_fields == 0
    assert report.total_fields == 9


def test_missing_malformed_refused_or_out_of_selection_observation_gets_no_credit() -> None:
    """Source-page admission and schema integrity apply before semantic field comparison."""
    malformed = observation()
    malformed.required_inputs.append("sales")
    refused = observation(
        status="refused",
        refusal_reason="No strategy.",
        refusal_category="insufficient_information",
        formula=None,
        required_inputs=[],
        long_short_direction=None,
        bucket_count=None,
        weighting=None,
        lookback_months=None,
        holding_months=None,
        rebalance_frequency=None,
        formation_lag_months=None,
        formation_rule=None,
    )
    for actual in (None, malformed, refused, observation(source_pages=[4])):
        assert grade_extraction(actual, gold(), "extracted").matched_fields == 0
    report = score_extractions(
        (gold(),),
        {"ratio": result("extracted", observation()).model_copy(update={"observation": malformed})},
    )
    assert report.cases[0].outcome == "invalid"
    assert report.attempted_cases == 1


def test_formula_absence_and_missing_vector_category_are_failures() -> None:
    """Null signals and valid syntax requesting an unavailable data category remain incorrect."""
    for formula in (None, "delta(sales)-cost/assets"):
        grade = grade_extraction(observation(formula=formula), gold(), "extracted")
        assert not grade.field_matches["formula"]


def test_delta_and_compound_names_use_full_predeclared_vectors() -> None:
    """Call target names are excluded while argument names and complete histories stay bound."""
    vectors = tuple(
        NumericalVector(
            name=f"history-{index}",
            deltas={"stock": ("10", ending)},
            series={"returns": ("0.9", "0.25", "-0.2", "0")},
            expected=expected,
        )
        for index, (ending, expected) in enumerate([("15", "5"), ("8", "-2"), ("11", "1")])
    )
    actual = observation(
        formula="delta(stock)+compound_return(returns,3)", required_inputs=["stock", "returns"]
    )
    case = GoldCase(
        case_id="history",
        paper_id="fictional",
        source_sha256="a" * 64,
        expected=actual,
        numerical_vectors=vectors,
        allowed_source_pages=(2,),
    )
    assert grade_extraction(actual, case, "extracted").all_critical_fields_match
    assert not grade_extraction(
        actual.model_copy(update={"formula": "delta(stock)+compound_return(returns,4)"}),
        case,
        "extracted",
    ).field_matches["formula"]
    assert case.numerical_vectors[0].series["returns"] == ("0.9", "0.25", "-0.2", "0")


@pytest.mark.parametrize(
    "mutation",
    [
        {"allowed_source_pages": (2, 2)},
        {"allowed_source_pages": (3,)},
        {"expected": observation(formula=None)},
        {"expected": observation(formula="sales/assets")},
        {"expected": observation(formula="-(sales-cost)/assets")},
        {"expected": observation(formula="abs(sales-cost)/assets")},
        {"expected": observation(required_inputs=["sales", "cost", "assets", "extra"])},
    ],
)
def test_inconsistent_gold_is_rejected_before_grading(mutation: dict[str, object]) -> None:
    """Gold is a reviewed contract rather than a way to bless missing or unexecutable formulas."""
    with pytest.raises(ValidationError):
        GoldCase.model_validate(gold().model_dump() | mutation)


def test_gold_requires_three_named_vectors_and_exact_decimal_answers() -> None:
    """No example is silently skipped, duplicated by name or accepted with a numeric tolerance."""
    case = gold()
    for vectors in (
        case.numerical_vectors[:2],
        (case.numerical_vectors[0],) * 3,
        (
            case.numerical_vectors[0].model_copy(
                update={"expected": "0.50000000000000000000000000000000000000000000000001"}
            ),
            *case.numerical_vectors[1:],
        ),
    ):
        with pytest.raises(ValidationError):
            GoldCase.model_validate(case.model_dump() | {"numerical_vectors": vectors})


def test_vector_schema_is_strict_bounded_and_unambiguous() -> None:
    """Decimal strings, disjoint input categories and total value budgets constrain saved gold."""
    for values in (
        {"scalars": {"value": 1}},
        {"scalars": {"value": "1"}, "deltas": {"value": ("0", "1")}},
        {"scalars": {f"v{i}": "1" for i in range(32)}, "deltas": {"change": ("0", "1")}},
        {"series": {f"v{i}": ("0",) * 1200 for i in range(4)}},
        {"deltas": {"value": ("0",)}},
        {"series": {"value": ("0",) * 1201}},
    ):
        with pytest.raises(ValidationError):
            NumericalVector.model_validate({"name": "bad", "expected": "0"} | values)


def test_report_reload_rejects_inconsistent_or_mutated_counts() -> None:
    """Strict revalidation rejects nested mutation and aggregate-only score edits."""
    report = score_extractions((gold(),), {"ratio": result("extracted", observation())})
    assert CriticalFieldReport.model_validate_json(report.canonical_bytes()).sha256 == report.sha256
    for update in (
        {"attempted_cases": 2},
        {"total_fields": 18},
        {"matched_fields": 0},
        {"critical_field_accuracy": 0.0},
        {"all_fields_case_accuracy": 0.0},
        {"cases": report.cases * 2},
    ):
        with pytest.raises(ValidationError):
            CriticalFieldReport.model_validate(report.model_dump() | update)
    grade = report.cases[0]
    grade_updates: tuple[dict[str, object], ...] = (
        {"field_matches": {}},
        {"matched_fields": 0},
        {"all_critical_fields_match": False},
        {"outcome": "provider_failed"},
    )
    for grade_update in grade_updates:
        with pytest.raises(ValidationError):
            CaseGrade.model_validate(grade.model_dump() | grade_update)
    grade.field_matches["formula"] = False
    with pytest.raises(ValidationError):
        report.canonical_bytes()


def test_copied_invalid_gold_and_unknown_outcomes_stop_evaluation() -> None:
    """Caller contract errors cannot masquerade as a recognized delivery failure."""
    case = gold().model_copy(update={"source_sha256": "invalid"})
    with pytest.raises(ResearchError) as failure:
        score_extractions((case,), {"ratio": result("extracted", observation())})
    assert failure.value.code == "EXTRACTION_EVAL_INVALID"
    invalid_outcomes: tuple[object, ...] = ("unknown", [], None)
    for outcome in invalid_outcomes:
        with pytest.raises(ResearchError):
            grade_extraction(observation(), gold(), cast(Outcome, outcome))
