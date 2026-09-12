"""Convert explicitly reviewed development attempts into SFT or DPO training records."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.factors import Contract
from factorforge.lineage.closure import verify_closure
from factorforge.lineage.trajectories import TrajectoryExport, export_trajectories


class Selection(Contract):
    """Review labels name retained attempts; operation success never supplies a reward."""

    chosen: str = Field(pattern=r"^[0-9a-f]{64}$")
    rejected: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rationale: str = Field(min_length=10, max_length=4000)


class Review(Contract):
    """An operator attests split ownership; byte and exact-prompt isolation are checked."""

    schema_version: Literal["training-review-v1"] = "training-review-v1"
    reviewer: str = Field(min_length=3, max_length=200)
    environment_version: str = Field(min_length=3, max_length=200)
    rubric_version: str = Field(min_length=3, max_length=200)
    development_only_attested: Literal[True]
    train_exports: list[ArtifactRef] = Field(min_length=1, max_length=128)
    heldout_exports: list[ArtifactRef] = Field(min_length=1, max_length=128)
    selections: list[Selection] = Field(min_length=1, max_length=10000)


def canonical(value: Any) -> bytes:
    """Use stable JSON bytes for prompt identities and retained preparation metadata."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def attempts(
    refs: list[ArtifactRef], store: LocalArtifactStore, *, training: bool
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Rebuild every export from its verified source, rejecting edited trajectory rows."""
    found: dict[str, dict[str, Any]] = {}
    runs: set[str] = set()
    for ref in refs:
        verify_closure(ref, store)
        export = TrajectoryExport.model_validate_json(store.get(ref))
        if training and export.request.partition != "development":
            raise ValueError("Evaluation exports cannot train a policy")
        if export_trajectories(export.request, store) != export:
            raise ValueError("Trajectory export differs from retained source")
        runs.add(str(export.run_id))
        for line in store.get(export.rows).splitlines():
            row = json.loads(line)
            for attempt in row["model_attempts"]:
                identity = attempt["provider_record"]["sha256"]
                if identity in found and found[identity] != attempt:
                    raise ValueError("Conflicting attempt identity")
                found[identity] = attempt
    return found, runs


def prepare(review: Review, store: LocalArtifactStore, mode: str) -> list[dict[str, Any]]:
    """Enforce run and exact-prompt disjointness; semantic overlap still needs review."""
    train, train_runs = attempts(review.train_exports, store, training=True)
    heldout, heldout_runs = attempts(review.heldout_exports, store, training=False)
    if not heldout:
        raise ValueError("Held-out inventory must contain recorded model prompts")
    if train_runs & heldout_runs:
        raise ValueError("Training and held-out research runs overlap")
    heldout_prompts = {canonical(item["messages"]) for item in heldout.values()}
    rows: list[dict[str, Any]] = []
    used: set[str] = set()
    for selection in review.selections:
        if selection.chosen in used:
            raise ValueError("Duplicate chosen attempt")
        used.add(selection.chosen)
        chosen = train[selection.chosen]
        prompt = chosen["messages"]
        if canonical(prompt) in heldout_prompts:
            raise ValueError("Training prompt overlaps held-out source")
        content = chosen["assistant_content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Chosen attempt has no retained response")
        answer = [{"role": "assistant", "content": content}]
        if mode == "sft":
            if selection.rejected is not None:
                raise ValueError("SFT review must not discard a preference label")
            rows.append(dict(prompt=prompt, completion=answer))
        elif mode == "dpo":
            if selection.rejected is None:
                raise ValueError("DPO requires a reviewed rejected attempt")
            rejected = train[selection.rejected]
            other = rejected["assistant_content"]
            if rejected["messages"] != prompt or not isinstance(other, str) or not other.strip():
                raise ValueError("DPO responses must share the exact recorded prompt")
            if other == content:
                raise ValueError("DPO responses must differ")
            rows.append(
                dict(
                    prompt=prompt, chosen=answer, rejected=[{"role": "assistant", "content": other}]
                )
            )
        else:
            raise ValueError("Unsupported training mode")
    return rows


def main() -> None:
    """Retain the review, verified export roots and exact training bytes in a fresh bundle."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--mode", choices=("sft", "dpo"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.review.open("rb") as source:
        raw = source.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Review exceeds 2 MiB")
    review = Review.model_validate_json(raw)
    rows = prepare(review, LocalArtifactStore(args.artifacts), args.mode)
    dataset = b"".join(canonical(row) + b"\n" for row in rows)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "train.jsonl").write_bytes(dataset)
    (args.output / "review.json").write_bytes(raw)
    manifest = dict(
        schema_version="training-bundle-v1",
        mode=args.mode,
        rows=len(rows),
        files={
            "train.jsonl": hashlib.sha256(dataset).hexdigest(),
            "review.json": hashlib.sha256(raw).hexdigest(),
        },
        promotion_status="candidate_only",
    )
    (args.output / "manifest.json").write_bytes(canonical(manifest))
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
