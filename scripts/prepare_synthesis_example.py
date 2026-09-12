"""Prepare original multi-source research inputs before any local model call."""

import argparse
from pathlib import Path

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.synthesis_fixture import prepare_synthesis_fixture
from factorforge.orchestration.synthesis_command import QwenSynthesisResearchRequest


def main() -> None:
    """Retain the complete source/data request exclusively; execution is a separate command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument(
        "--profile", choices=("original-v1", "qwen-extraction-v1"), default="original-v1"
    )
    parser.add_argument("--source-literal-timing", action="store_true")
    args = parser.parse_args()
    request = prepare_synthesis_fixture(
        Path(__file__).resolve().parents[1], LocalArtifactStore(args.artifacts)
    )
    if args.profile == "qwen-extraction-v1":
        request = QwenSynthesisResearchRequest.model_validate_json(
            request.model_copy(
                update={"schema_version": "synthesis-research-request-v2"}
            ).model_dump_json()
        )
    if args.source_literal_timing:
        request = request.model_copy(
            update={
                "bindings": tuple(
                    binding.model_copy(
                        update={"reviewed_formation_rule": binding.reviewed_formation_rule + "."}
                    )
                    for binding in request.bindings
                )
            }
        )
    with args.request.open("xb") as output:
        output.write(request.canonical_bytes())
    print(request.sha256)


if __name__ == "__main__":
    main()
