"""Compare matching frozen development evaluations without silently changing their denominator."""

import argparse
from pathlib import Path

from factorforge.evaluation.directions import DirectionEvaluation, DirectionSuite, grade_direction


def verify_grades(suite: DirectionSuite, evaluation: DirectionEvaluation) -> None:
    """Recompute saved scores against frozen source labels before using them in a CI decision."""
    suite = DirectionSuite.model_validate(suite)
    evaluation = DirectionEvaluation.model_validate(evaluation)
    if (
        evaluation.suite.sha256 != suite.sha256
        or evaluation.suite.size_bytes != len(suite.canonical_bytes())
        or evaluation.suite.media_type != "application/json"
        or tuple(g.case_id for g in evaluation.grades) != tuple(c.case_id for c in suite.cases)
    ):
        raise ValueError("Evaluation does not match the frozen suite")
    if any(
        grade_direction(case, grade.observation) != grade
        for case, grade in zip(suite.cases, evaluation.grades, strict=True)
    ):
        raise ValueError("Saved grades do not match the frozen rubric")


def regressed(baseline: DirectionEvaluation, candidate: DirectionEvaluation) -> bool:
    """Reject a relative pass-count regression of at least five percent on identical cases."""
    baseline = DirectionEvaluation.model_validate(baseline)
    candidate = DirectionEvaluation.model_validate(candidate)
    if baseline.suite != candidate.suite or tuple(g.case_id for g in baseline.grades) != tuple(
        g.case_id for g in candidate.grades
    ):
        raise ValueError("Evaluation suite or ordered cases differ")
    before = sum(grade.passed for grade in baseline.grades)
    after = sum(grade.passed for grade in candidate.grades)
    return before > 0 and (before - after) * 20 >= before


def main() -> None:
    """Use saved artifacts for CI; this check never starts a live model during a build."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument(
        "--cases", type=Path, default=Path(__file__).parent / "cases/custom/direction-v1.json"
    )
    args = parser.parse_args()
    with args.cases.open("rb") as source:
        suite_raw = source.read(256 * 1024 + 1)
    if len(suite_raw) > 256 * 1024:
        raise ValueError("Evaluation suite exceeds limit")
    suite = DirectionSuite.model_validate_json(suite_raw)
    values = []
    for path in (args.baseline, args.candidate):
        with path.open("rb") as source:
            raw = source.read(2**20 + 1)
        if len(raw) > 2**20:
            raise ValueError("Evaluation artifact exceeds limit")
        values.append(DirectionEvaluation.model_validate_json(raw))
        verify_grades(suite, values[-1])
    raise SystemExit(1 if regressed(values[0], values[1]) else 0)


if __name__ == "__main__":
    main()
