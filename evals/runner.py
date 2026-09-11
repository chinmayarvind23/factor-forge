"""Run the frozen original direction suite with retained per-case provider evidence."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.evaluation.directions import (
    DirectionEvaluation,
    DirectionSuite,
    evaluate_directions,
)
from factorforge.orchestration.research_strategies import _publish
from factorforge.providers.ollama import OllamaProvider
from factorforge.retrieval.direction_review import REVIEW_PROMPT


def main() -> None:
    """Reserve one journal before live inference and retain each case before advancing."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases", type=Path, default=Path(__file__).parent / "cases/custom/direction-v1.json"
    )
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.cases.open("rb") as source:
        raw = source.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError("Evaluation suite exceeds limit")
    suite = DirectionSuite.model_validate_json(raw)
    artifacts = LocalArtifactStore(args.artifacts)
    suite_ref = _publish(suite, artifacts)
    prompt_sha = hashlib.sha256(REVIEW_PROMPT.encode()).hexdigest()
    with args.output.open("xb") as journal:
        journal.write(
            json.dumps(
                {
                    "status": "started",
                    "suite": suite_ref.model_dump(mode="json"),
                    "prompt_sha256": prompt_sha,
                    "max_wall_seconds": 600,
                }
            ).encode()
            + b"\n"
        )
        journal.flush()
        grades = []
        provider = OllamaProvider(deadline=time.monotonic() + 600)
        for grade in evaluate_directions(suite, provider, artifacts):
            grades.append(grade)
            row = {
                "case_id": grade.case_id,
                "grade": _publish(grade, artifacts).model_dump(mode="json"),
            }
            journal.write(json.dumps(row).encode() + b"\n")
            journal.flush()
            print(json.dumps({"case_id": grade.case_id, "passed": grade.passed}), flush=True)
        result = DirectionEvaluation(
            suite=suite_ref, prompt_sha256=prompt_sha, grades=tuple(grades)
        )
        reference = _publish(result, artifacts)
        final = {
            "status": "recorded",
            "evaluation": reference.model_dump(mode="json"),
            "passed": sum(grade.passed for grade in grades),
            "total": len(grades),
        }
        journal.write(json.dumps(final).encode() + b"\n")
        print(json.dumps(final), flush=True)


if __name__ == "__main__":
    main()
