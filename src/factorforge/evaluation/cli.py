"""Run a frozen retrieval evaluation and archive its complete local execution inputs."""

import argparse
import importlib
import json
import math
import platform
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from pydantic import BaseModel

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.evaluation.retrieval import (
    RetrievalCorpus,
    RetrievalJudgments,
    evaluate_retrieval,
)

MAX_INPUT_BYTES = 16 * 1024 * 1024
CODE_MODULES = (
    "factorforge.evaluation.cli",
    "factorforge.evaluation.retrieval",
    "factorforge.domain.literature",
    "factorforge.retrieval.lexical",
    "factorforge.domain.errors",
    "factorforge.domain.artifacts",
    "factorforge.data.artifacts",
)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Duplicate input keys must not disappear during model parsing."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _finite(value: str) -> float:
    """Reject named or overflowing nonfinite numbers even if an input schema later ignores them."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Nonfinite JSON number")
    return number


def _load[Model: BaseModel](path: Path, model: type[Model]) -> tuple[Model, bytes]:
    """Read a bounded local JSON snapshot and validate it before creating evaluation artifacts."""
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("Input byte limit")
        text = raw.decode("utf-8")
        # Preflight rejects ambiguity and nonfinite values; JSON-mode validation accepts arrays
        # for immutable tuple fields without permitting string-to-number coercion.
        json.loads(text, object_pairs_hook=_pairs, parse_float=_finite, parse_constant=_finite)
        return model.model_validate_json(raw, strict=True), raw
    except (OSError, ValueError, RecursionError, OverflowError):
        raise ResearchError(
            "RETRIEVAL_INPUT_INVALID", "Retrieval input is unavailable or invalid.", 422
        ) from None


def _save(store: ArtifactStore, value: object) -> ArtifactRef:
    """Persist portable JSON bytes and return the verified store's immutable identity."""
    return store.put(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8"),
        media_type="application/json",
    )


def run_evaluation(
    corpus_path: Path, qrels_path: Path, store: ArtifactStore, *, k: int = 3
) -> dict[str, object]:
    """Preserve actual source snapshots and dependency versions alongside every ranked result."""
    corpus, corpus_raw = _load(corpus_path, RetrievalCorpus)
    qrels, qrels_raw = _load(qrels_path, RetrievalJudgments)
    started_at = datetime.now(UTC).isoformat()
    started = time.monotonic()
    report = evaluate_retrieval(corpus, qrels, k=k)
    elapsed_ms = round((time.monotonic() - started) * 1000, 3)
    code: dict[str, dict[str, object]] = {}
    try:
        package_versions = {
            name: version(name) for name in ("factorforge", "pydantic", "pydantic_core")
        }
        for name in CODE_MODULES:
            module = importlib.import_module(name)
            if module.__file__ is None:
                raise OSError("Source module unavailable")
            raw = Path(module.__file__).read_text(encoding="utf-8").encode("utf-8")
            code[name] = store.put(raw, media_type="text/x-python").model_dump(mode="json")
    except (ImportError, OSError, UnicodeError):
        raise ResearchError(
            "RETRIEVAL_LINEAGE_INVALID",
            "Installed source or dependency evidence is unavailable.",
            503,
        ) from None
    components = {
        "corpus": store.put(corpus_raw, media_type="application/json"),
        "qrels": store.put(qrels_raw, media_type="application/json"),
        "config": _save(
            store,
            {
                "algorithm": "bm25-v1",
                "k": k,
                "k1": 1.2,
                "b": 0.75,
                "threshold": "positive_score",
                "query_terms": "deduplicated",
            },
        ),
        "report": _save(store, report.model_dump(mode="json")),
        "environment": _save(
            store,
            {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "packages": package_versions,
            },
        ),
    }
    record = _save(
        store,
        {
            "schema_version": "retrieval-evaluation-v1",
            "text_identity": "utf8-lf-v1",
            "started_at": started_at,
            "evaluation_ms": elapsed_ms,
            **{name: reference.model_dump(mode="json") for name, reference in components.items()},
            "code": code,
        },
    )
    return {"record": record.model_dump(mode="json"), "report": report.model_dump(mode="json")}


def main(argv: Sequence[str] | None = None) -> int:
    """Print report and evidence pointer only after all required artifacts are stored."""
    parser = argparse.ArgumentParser(description="Evaluate a frozen literature retrieval corpus.")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        result = run_evaluation(args.corpus, args.qrels, LocalArtifactStore(args.output), k=args.k)
        print(json.dumps(result, sort_keys=True))
        return 0
    except ResearchError as error:
        print(
            json.dumps({"error": {"code": error.code, "message": error.message}}), file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
