"""Verify actual Deep Agents and PostgreSQL boundaries using explicit controlled responses."""

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from planner import propose

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.providers.ollama import GenerationRequest, GenerationResult, OllamaProvider


def main() -> None:
    """Use a fresh test schema; never call a model or open host files through the planner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir()
    schema = "ff_test_" + uuid4().hex
    runs = PostgresRunStore(
        os.environ["FACTORFORGE_TEST_DSN"], schema=schema, require_test_database=True
    )
    outcomes = []
    try:
        for case in ("notebook", "invalid_action", "repeat_note", "budget", "interrupted"):
            store = LocalArtifactStore(args.output / case)
            calls: list[dict[str, Any]] = []

            def generate(
                self: OllamaProvider,
                request: GenerationRequest,
                artifacts: ArtifactStore,
                *,
                scenario: str = case,
                recorded: list[dict[str, Any]] = calls,
            ) -> GenerationResult:
                """Return labelled observations; this verifier measures framework behavior only."""
                recorded.append(request.model_dump(mode="json"))
                answer: dict[str, Any]
                if scenario == "interrupted":
                    raise RuntimeError("Controlled interruption")
                if scenario == "invalid_action":
                    answer = dict(action="execute", note="forbidden", plan=None)
                elif len(recorded) == 1 or scenario == "repeat_note":
                    answer = dict(
                        action="write_note", note="Check point-in-time source evidence.", plan=None
                    )
                else:
                    answer = dict(
                        action="finish",
                        note=None,
                        plan=dict(
                            queries=["momentum costs"],
                            hypotheses=["Momentum persists after costs."],
                            validation_steps=[
                                "Check timing, costs, time-series validation and LEAN."
                            ],
                        ),
                    )
                return GenerationResult(
                    status="success",
                    content=json.dumps({"decision": answer}),
                    record=artifacts.put(b'{"controlled":true}', media_type="application/json"),
                )

            brief = ResearchBrief(
                idea="Original planning boundary: " + case,
                max_llm_cost_usd=Decimal("0.50") if case == "budget" else Decimal("5.00"),
            )
            with patch.object(OllamaProvider, "generate", generate):
                result = propose(brief, runs, store)
            with patch.object(
                OllamaProvider, "generate", side_effect=AssertionError("No redispatch")
            ):
                replay = propose(brief, runs, store)
            assert result.status == replay.status == ("proposed" if case == "notebook" else "held")
            assert (
                len(calls)
                == {
                    "notebook": 2,
                    "repeat_note": 2,
                    "invalid_action": 1,
                    "budget": 0,
                    "interrupted": 1,
                }[case]
            )
            if case == "notebook":
                assert result == replay
                assert "Updated file /research-plan.md" in calls[1]["user"]
                assert "Check point-in-time source evidence." in calls[1]["user"]
            (args.output / (case + ".json")).write_text(result.model_dump_json(indent=2))
            outcomes.append(
                dict(case=case, status=result.status, calls=len(calls), replay_no_dispatch=True)
            )
        (args.output / "verification.json").write_text(
            json.dumps(dict(schema=schema, controlled_provider=True, cases=outcomes), indent=2)
        )
        print(json.dumps(outcomes))
    finally:
        runs.close()


if __name__ == "__main__":
    main()
