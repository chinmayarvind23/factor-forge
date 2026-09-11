"""Gold labels stay outside model inputs and joint scores reject unsupported conclusions."""

import json
from pathlib import Path

import pytest
from test_monthly_admission import MemoryStore

from evals.ci_gate import regressed
from factorforge.data.artifacts import ArtifactStore
from factorforge.evaluation.directions import (
    DirectionEvaluation,
    DirectionGrade,
    DirectionSuite,
    evaluate_directions,
    grade_direction,
)
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from factorforge.retrieval.direction_review import DirectionObservation, DirectionReview


def suite() -> DirectionSuite:
    """Use the committed original cases and their predeclared support anchors."""
    return DirectionSuite.model_validate_json(
        (Path(__file__).resolve().parents[2] / "evals/cases/custom/direction-v1.json").read_bytes()
    )


@pytest.mark.parametrize(
    "direction,quote,correct,supported",
    [
        (
            "long_high_short_low",
            "Buy high-score securities and short low-score securities",
            True,
            True,
        ),
        (
            "long_low_short_high",
            "Buy high-score securities and short low-score securities",
            False,
            True,
        ),
        ("long_high_short_low", "Signal Alpha", True, False),
        (
            "long_high_short_low",
            "Invented Buy high-score securities and short low-score securities",
            True,
            False,
        ),
    ],
)
def test_direction_and_quote_support_are_separate(
    direction: str, quote: str, correct: bool, supported: bool
) -> None:
    """A real substring or a correct direction alone cannot pass the joint rubric."""
    store = MemoryStore()
    result = DirectionReview.model_validate(
        {
            "status": "supported",
            "observation": {
                "direction": direction,
                "quote": quote,
                "pdf_page": 1,
                "uncertainty": None,
            },
            "record": store.put(b"{}", media_type="application/json"),
        }
    )
    grade = grade_direction(suite().cases[0], result)
    assert (grade.direction_correct, grade.quote_supported, grade.passed) == (
        correct,
        supported,
        correct and supported,
    )


def test_abstention_requires_an_actual_uncertain_observation() -> None:
    """Provider absence is not credited as a correctly identified ambiguity."""
    store = MemoryStore()
    ref = store.put(b"{}", media_type="application/json")
    uncertain = DirectionReview(
        status="uncertain",
        record=ref,
        observation=DirectionObservation(
            direction=None, quote=None, pdf_page=None, uncertainty="No direction is specified"
        ),
    )
    assert grade_direction(suite().cases[4], uncertain).passed
    absent = DirectionReview(status="provider_failed", record=ref, observation=None)
    assert not grade_direction(suite().cases[4], absent).passed


def test_gold_changes_do_not_change_the_model_request() -> None:
    """Labels affect grading only, even when a deliberately changed label disagrees with source."""
    store = MemoryStore()
    first = suite().cases[0]
    calls = []

    class Provider:
        """Controlled response exposes exactly what enters the model boundary."""

        def generate(
            self, request: GenerationRequest, artifacts: ArtifactStore
        ) -> GenerationResult:
            """Record the prompt and return a source-based observation independent of gold."""
            calls.append(request)
            assert set(json.loads(request.user)) == {"selected_strategy", "pages"}
            return GenerationResult(
                status="success",
                record=artifacts.put(b"{}", media_type="application/json"),
                content=json.dumps(
                    {
                        "direction": "long_high_short_low",
                        "quote": first.support_anchors[0],
                        "pdf_page": 1,
                        "uncertainty": None,
                    }
                ),
            )

    original = list(evaluate_directions(DirectionSuite(cases=(first,)), Provider(), store))
    changed = first.model_copy(update={"expected_direction": "long_low_short_high"})
    alternate = list(evaluate_directions(DirectionSuite(cases=(changed,)), Provider(), store))
    assert calls[0] == calls[1] and original[0].passed and not alternate[0].passed


@pytest.mark.parametrize("passes,rejected", [(20, False), (19, True), (18, True)])
def test_regression_gate_uses_the_frozen_denominator(passes: int, rejected: bool) -> None:
    """One lost case out of twenty is exactly the declared five-percent threshold."""
    store = MemoryStore()
    ref = store.put(b"{}", media_type="application/json")
    observed = DirectionReview(status="provider_failed", observation=None, record=ref)
    grades = tuple(
        DirectionGrade(
            case_id=f"case-{index}",
            observation=observed,
            direction_correct=True,
            quote_supported=True,
            passed=True,
        )
        for index in range(20)
    )
    baseline = DirectionEvaluation(suite=ref, prompt_sha256="a" * 64, grades=grades)
    candidate = baseline.model_copy(
        update={
            "grades": tuple(
                grade
                if index < passes
                else grade.model_copy(
                    update={"direction_correct": False, "quote_supported": False, "passed": False}
                )
                for index, grade in enumerate(grades)
            )
        }
    )
    assert regressed(baseline, candidate) == rejected
    with pytest.raises(ValueError):
        regressed(
            baseline,
            candidate.model_copy(update={"suite": ref.model_copy(update={"sha256": "b" * 64})}),
        )
