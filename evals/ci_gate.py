"""Compare matching frozen development evaluations without silently changing their denominator."""

import argparse
from pathlib import Path

from factorforge.evaluation.directions import DirectionEvaluation


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
    args = parser.parse_args()
    values = []
    for path in (args.baseline, args.candidate):
        with path.open("rb") as source:
            raw = source.read(2**20 + 1)
        if len(raw) > 2**20:
            raise ValueError("Evaluation artifact exceeds limit")
        values.append(DirectionEvaluation.model_validate_json(raw))
    raise SystemExit(1 if regressed(values[0], values[1]) else 0)


if __name__ == "__main__":
    main()
