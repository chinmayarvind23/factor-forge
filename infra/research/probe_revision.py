"""Run one explicitly retained local quote-first experiment outside production run scheduling."""

import argparse
import json
import time
from pathlib import Path

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.orchestration.research_strategies import _publish
from factorforge.providers.ollama import OllamaProvider
from factorforge.retrieval.direction_revision import DirectionRevisionRequest
from factorforge.retrieval.quote_first_revision import revise_direction_quote_first


def main() -> None:
    """Reserve an exclusive receipt before one attempt; preserve a started row on interruption."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-only", action="store_true")
    args = parser.parse_args()
    with args.request.open("rb") as source:
        raw = source.read(4 * 2**20 + 1)
    if len(raw) > 4 * 2**20:
        raise ValueError("Probe request exceeds limit")
    request = DirectionRevisionRequest.model_validate_json(raw)
    store = LocalArtifactStore(args.artifacts)
    request_ref = _publish(request, store)
    with args.output.open("xb") as receipt:
        started = {
            "profile": "source-only-quote-first-revision-probe-v1"
            if args.source_only
            else "quote-first-revision-probe-v1",
            "status": "started",
            "request": request_ref.model_dump(mode="json"),
            "max_wall_seconds": 180,
        }
        receipt.write(json.dumps(started, sort_keys=True).encode() + b"\n")
        receipt.flush()
        result = revise_direction_quote_first(
            request,
            OllamaProvider(deadline=time.monotonic() + 180),
            store,
            context="source_only" if args.source_only else "conflict",
        )
        reference = _publish(result, store)
        completed = {"status": "recorded", "result": reference.model_dump(mode="json")}
        receipt.write(json.dumps(completed, sort_keys=True).encode() + b"\n")
    print(json.dumps(result.model_dump(mode="json")))


if __name__ == "__main__":
    main()
