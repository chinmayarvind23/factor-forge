"""Critical-field pilot grading uses frozen examples, not symbolic or empirical equivalence.

Formation prose is archived but not graded. Citation bounds admit observations without
asserting that a passage entails them. Every attempted case contributes nine field decisions.
"""

import ast
import hashlib
import json
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from factorforge.domain.errors import ResearchError
from factorforge.domain.extraction import SourceExtraction
from factorforge.domain.formula import evaluate_formula, parse_formula
from factorforge.retrieval.extraction import ExtractionResult

type Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
type InputName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
type DecimalText = Annotated[str, Field(min_length=1, max_length=128)]
type Outcome = Literal["extracted", "refused", "invalid", "provider_failed", "input_rejected"]
OUTCOMES = frozenset({"extracted", "refused", "invalid", "provider_failed", "input_rejected"})
CRITICAL_FIELDS = (
    "formula",
    "required_inputs",
    "long_short_direction",
    "bucket_count",
    "weighting",
    "lookback_months",
    "holding_months",
    "rebalance_frequency",
    "formation_lag_months",
)


class _Canonical(BaseModel):
    """Revalidation precedes hashing because frozen models can still contain mutable containers."""

    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always"
    )

    def canonical_bytes(self) -> bytes:
        """Canonical UTF-8 JSON includes every declared field and preserves full input arrays."""
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
        """The content digest binds a versioned case or report without claiming authentication."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class NumericalVector(_Canonical):
    """Decimal strings encode scalars, beginning/ending pairs and full oldest/newest arrays."""

    name: Identifier
    scalars: Annotated[dict[InputName, DecimalText], Field(max_length=32)] = Field(
        default_factory=dict
    )
    deltas: Annotated[dict[InputName, tuple[DecimalText, DecimalText]], Field(max_length=32)] = (
        Field(default_factory=dict)
    )
    series: Annotated[
        dict[InputName, Annotated[tuple[DecimalText, ...], Field(min_length=1, max_length=1200)]],
        Field(max_length=32),
    ] = Field(default_factory=dict)
    expected: DecimalText

    @model_validator(mode="after")
    def valid_numbers(self) -> Self:
        """Validate all values, including unused array prefixes, under the interpreter's bounds."""
        names = set(self.scalars) | set(self.deltas) | set(self.series)
        if len(names) != len(self.scalars) + len(self.deltas) + len(self.series):
            raise ValueError("Vector input categories must be disjoint")
        if len(names) > 32:
            raise ValueError("Vector input inventory exceeds its limit")
        try:
            evaluate_formula("0", scalars=self.scalars, deltas=self.deltas, series=self.series)
            evaluate_formula("answer", scalars={"answer": self.expected})
        except ResearchError as error:
            raise ValueError("Vector numbers are invalid") from error
        return self


def _input_names(expression: str) -> set[str]:
    """Exclude only call-target AST nodes, retaining scalar names and named function arguments."""
    tree = parse_formula(expression)
    call_targets = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and id(node) not in call_targets
    }


def _matches_vectors(expression: str, vectors: tuple[NumericalVector, ...]) -> bool:
    """Every predeclared example must match exactly, without tolerance or expression repair."""
    return all(
        evaluate_formula(
            expression, scalars=vector.scalars, deltas=vector.deltas, series=vector.series
        )
        == Decimal(vector.expected)
        for vector in vectors
    )


class GoldCase(_Canonical):
    """A frozen source selection and three reviewed vectors precede any model observation."""

    schema_version: Literal["critical-field-gold-v1"] = "critical-field-gold-v1"
    case_id: Identifier
    paper_id: Identifier
    source_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    expected: SourceExtraction
    numerical_vectors: Annotated[tuple[NumericalVector, ...], Field(min_length=3, max_length=3)]
    allowed_source_pages: Annotated[
        tuple[Annotated[int, Field(ge=1, le=10000)], ...], Field(min_length=1, max_length=16)
    ]

    @model_validator(mode="after")
    def complete_gold(self) -> Self:
        """Reject inconsistent source bounds, unsupported fields and incorrect fixture answers."""
        expected = self.expected
        mandatory = (
            expected.formula,
            expected.long_short_direction,
            expected.bucket_count,
            expected.weighting,
            expected.holding_months,
            expected.rebalance_frequency,
        )
        if expected.status != "extracted" or any(value is None for value in mandatory):
            raise ValueError("Gold requires a complete extracted critical-field observation")
        if len(set(self.allowed_source_pages)) != len(self.allowed_source_pages):
            raise ValueError("Gold source pages must be unique")
        if not set(expected.source_pages) <= set(self.allowed_source_pages):
            raise ValueError("Gold citations exceed its selected pages")
        if len({vector.name for vector in self.numerical_vectors}) != 3:
            raise ValueError("Gold numerical vector names must be unique")
        required = set(expected.required_inputs)
        for vector in self.numerical_vectors:
            if set(vector.scalars) | set(vector.deltas) | set(vector.series) != required:
                raise ValueError("Gold vector inputs must equal required inputs")
        assert expected.formula is not None
        try:
            if _input_names(expected.formula) != required:
                raise ValueError("Gold formula inputs must equal required inputs")
            if not _matches_vectors(expected.formula, self.numerical_vectors):
                raise ValueError("Gold formula disagrees with a numerical vector")
        except ResearchError as error:
            raise ValueError("Gold formula or its numerical vectors are invalid") from error
        return self


class CaseGrade(_Canonical):
    """Named booleans retain failures and observed formation prose without grading that prose."""

    case_id: Identifier
    paper_id: Identifier
    gold_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    outcome: Outcome
    field_matches: dict[str, bool]
    matched_fields: Annotated[int, Field(ge=0, le=9)]
    total_fields: Literal[9] = 9
    all_critical_fields_match: bool
    formation_rule_observed: Annotated[str, Field(max_length=2000)] | None

    @model_validator(mode="after")
    def consistent_fields(self) -> Self:
        """A saved or copied score must retain all nine checks and an honest failure count."""
        if set(self.field_matches) != set(CRITICAL_FIELDS):
            raise ValueError("A case grade requires exactly the nine critical fields")
        if self.matched_fields != sum(self.field_matches.values()):
            raise ValueError("Case field count disagrees with named checks")
        if self.all_critical_fields_match != (self.matched_fields == 9):
            raise ValueError("Case success disagrees with named checks")
        if self.outcome != "extracted" and self.matched_fields:
            raise ValueError("Failed attempts cannot receive field credit")
        return self


class CriticalFieldReport(_Canonical):
    """This tiny development metric is neither full FactorSpec accuracy nor a release claim."""

    name: Literal["critical_field_pilot"] = "critical_field_pilot"
    schema_version: Literal["critical-field-report-v1"] = "critical-field-report-v1"
    cases: Annotated[tuple[CaseGrade, ...], Field(min_length=1, max_length=1000)]
    attempted_cases: Annotated[int, Field(ge=1, le=1000)]
    matched_fields: Annotated[int, Field(ge=0)]
    total_fields: Annotated[int, Field(ge=9)]
    critical_field_accuracy: Annotated[float, Field(ge=0, le=1)]
    all_fields_case_accuracy: Annotated[float, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def consistent_denominators(self) -> Self:
        """Canonical reports cannot drop a failed row or invent aggregate accuracy on reload."""
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Report case identifiers must be unique")
        if self.attempted_cases != len(self.cases) or self.total_fields != 9 * len(self.cases):
            raise ValueError("Report denominators disagree with its attempted cases")
        if self.matched_fields != sum(case.matched_fields for case in self.cases):
            raise ValueError("Report field count disagrees with its cases")
        if self.critical_field_accuracy != self.matched_fields / self.total_fields:
            raise ValueError("Report field accuracy disagrees with its counts")
        if self.all_fields_case_accuracy != (
            sum(case.all_critical_fields_match for case in self.cases) / self.attempted_cases
        ):
            raise ValueError("Report case accuracy disagrees with its counts")
        return self


def _invalid() -> ResearchError:
    """Gold and inventory failures stop evaluation instead of manufacturing a favorable score."""
    return ResearchError(
        "EXTRACTION_EVAL_INVALID", "Extraction evaluation gold or case inventory is invalid.", 422
    )


def grade_extraction(
    observation: SourceExtraction | None, gold: GoldCase, outcome: Outcome
) -> CaseGrade:
    """Ineligible or malformed attempts score zero; valid observations receive nine exact checks."""
    try:
        gold = GoldCase.model_validate(gold)
    except ValidationError:
        raise _invalid() from None
    if not isinstance(outcome, str) or outcome not in OUTCOMES:
        raise _invalid()
    try:
        actual = SourceExtraction.model_validate(observation) if observation is not None else None
    except ValidationError:
        actual = None
    matches = dict.fromkeys(CRITICAL_FIELDS, False)
    eligible = (
        outcome == "extracted"
        and actual is not None
        and actual.status == "extracted"
        and set(actual.source_pages) <= set(gold.allowed_source_pages)
    )
    if eligible:
        assert actual is not None
        for field in CRITICAL_FIELDS[2:]:
            matches[field] = getattr(actual, field) == getattr(gold.expected, field)
        matches["required_inputs"] = set(actual.required_inputs) == set(
            gold.expected.required_inputs
        )
        if actual.formula is not None:
            try:
                matches["formula"] = _input_names(actual.formula) == set(
                    actual.required_inputs
                ) and _matches_vectors(actual.formula, gold.numerical_vectors)
            except ResearchError:
                matches["formula"] = False
    matched = sum(matches.values())
    return CaseGrade(
        case_id=gold.case_id,
        paper_id=gold.paper_id,
        gold_sha256=gold.sha256,
        outcome=outcome,
        field_matches=matches,
        matched_fields=matched,
        all_critical_fields_match=matched == 9,
        formation_rule_observed=actual.formation_rule if actual is not None else None,
    )


def score_extractions(
    cases: tuple[GoldCase, ...], attempts: dict[str, ExtractionResult]
) -> CriticalFieldReport:
    """Require exactly one retained attempt per frozen case, including every failed delivery."""
    if (
        not isinstance(cases, tuple)
        or not 1 <= len(cases) <= 1000
        or not isinstance(attempts, dict)
    ):
        raise _invalid()
    try:
        cases = tuple(GoldCase.model_validate(case) for case in cases)
    except ValidationError:
        raise _invalid() from None
    identifiers = {case.case_id for case in cases}
    if len(identifiers) != len(cases) or set(attempts) != identifiers:
        raise _invalid()
    grades: list[CaseGrade] = []
    for case in cases:
        try:
            attempt = ExtractionResult.model_validate(attempts[case.case_id])
        except ValidationError:
            grades.append(grade_extraction(None, case, "invalid"))
        else:
            grades.append(grade_extraction(attempt.observation, case, attempt.status))
    matched = sum(grade.matched_fields for grade in grades)
    total = 9 * len(grades)
    return CriticalFieldReport(
        cases=tuple(grades),
        attempted_cases=len(grades),
        matched_fields=matched,
        total_fields=total,
        critical_field_accuracy=matched / total,
        all_fields_case_accuracy=sum(grade.all_critical_fields_match for grade in grades)
        / len(grades),
    )
