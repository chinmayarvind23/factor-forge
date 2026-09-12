"""Freeze and run one named model on an existing paper-development suite, without retries."""

import argparse
import json
from pathlib import Path

from factorforge.data.artifacts import LocalArtifactStore, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.evaluation.extraction import GoldCase, score_extractions
from factorforge.evaluation.source_trial import run_source_trial
from factorforge.lineage.closure import verify_closure
from factorforge.observability import local_trace
from factorforge.providers.ollama import GenerationRequest, _request_payload
from factorforge.retrieval.extraction import ExtractionResult, SourcePacket, prepare_prompt


def main() -> None:
    """Prepare every wire request before inference and retain each terminal case independently."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=("llama3.1:8b", "qwen3:8b"), required=True)
    args = parser.parse_args()
    baseline = LocalArtifactStore(args.baseline / "objects")
    prepared = json.loads((args.baseline / "prepared-gold-v1.json").read_bytes())
    cases = tuple(
        GoldCase.model_validate_json(baseline.get(ArtifactRef.model_validate(row["gold"])))
        for row in prepared["cases"]
    )
    if not 1 <= len(cases) <= 15 or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Suite must have one to fifteen unique frozen cases")
    args.output.mkdir(parents=True, exist_ok=False)
    store = LocalArtifactStore(args.output / "objects")
    inputs = []
    for index, case in enumerate(cases):
        packet_raw = (args.baseline / "case-inputs" / f"{case.paper_id}-packet.json").read_bytes()
        packet = SourcePacket.model_validate_json(packet_raw)
        for page in packet.pages:
            raw = baseline.get(page.artifact)
            verify_bytes(raw, page.artifact)
            if store.put(raw, media_type=page.artifact.media_type) != page.artifact:
                raise ValueError("Page identity changed during copy")
        prompt = prepare_prompt(packet, store)
        request = GenerationRequest.model_validate(dict(model=args.model, **prompt))
        wire = store.put(_request_payload(request)[1], media_type="application/json")
        paths = [args.output / f"{index}-{name}.json" for name in ("packet", "gold", "wire")]
        for path, raw in zip(
            paths,
            (packet_raw, case.canonical_bytes(), wire.model_dump_json().encode()),
            strict=True,
        ):
            with path.open("xb") as output:
                output.write(raw)
        inputs.append(paths)
    with (args.output / "freeze.json").open("x", encoding="utf-8") as output:
        json.dump(
            {
                "model": args.model,
                "attempts_per_case": 1,
                "scope": "existing-paper-development-comparison",
                "inputs": [
                    {
                        path.name: store.put(
                            path.read_bytes(), media_type="application/json"
                        ).model_dump()
                        for path in paths
                    }
                    for paths in inputs
                ],
            },
            output,
            indent=2,
        )
    attempts = {}
    trials = []
    with local_trace(args.output / "traces.jsonl"):
        for case, paths in zip(cases, inputs, strict=True):
            print(json.dumps({"event": "starting", "case": case.case_id}), flush=True)
            result = run_source_trial(paths[0], paths[1], paths[2], store, model=args.model)
            with (args.output / f"{case.paper_id}-result.json").open(
                "x", encoding="utf-8"
            ) as output:
                json.dump(result, output, indent=2)
            attempts[case.case_id] = ExtractionResult.model_validate(result["result"])
            trials.append(result["record"])
            print(
                json.dumps({"event": "completed", "case": case.case_id, "grade": result["grade"]}),
                flush=True,
            )
    report = score_extractions(cases, attempts)
    report_ref = store.put(report.canonical_bytes(), media_type="application/json")
    with (args.output / "report.json").open("xb") as output:
        output.write(report.canonical_bytes())
    bundle = store.put(
        json.dumps(
            {
                "schema_version": "extraction-comparison-v1",
                "model": args.model,
                "freeze": store.put(
                    (args.output / "freeze.json").read_bytes(), media_type="application/json"
                ).model_dump(),
                "runner": store.put(
                    Path(__file__).read_bytes(), media_type="text/x-python"
                ).model_dump(),
                "traces": store.put(
                    (args.output / "traces.jsonl").read_bytes(), media_type="application/x-ndjson"
                ).model_dump(),
                "trials": trials,
                "report": report_ref.model_dump(),
            },
            sort_keys=True,
        ).encode(),
        media_type="application/json",
    )
    closure = verify_closure(bundle, store)
    with (args.output / "verification.json").open("x", encoding="utf-8") as output:
        json.dump(
            {"bundle": bundle.model_dump(), "closure_objects": len(closure)}, output, indent=2
        )
    print(report.canonical_bytes().decode(), flush=True)


if __name__ == "__main__":
    main()
