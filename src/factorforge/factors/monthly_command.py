"""Archive a conditional monthly source-to-target calculation with explicit failure outcomes."""

import argparse
import importlib
import json
import platform
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.data.monthly_signals import MAX_SOURCE_BYTES, assemble_monthly_signals
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import PortfolioSpec
from factorforge.domain.monthly_signals import MonthlySignalRequest
from factorforge.factors.targets import build_targets

CODE_MODULES = (
    "factorforge",
    "factorforge.factors.monthly_command",
    "factorforge.factors.targets",
    "factorforge.data.artifacts",
    "factorforge.data.point_in_time",
    "factorforge.data.monthly_signals",
    "factorforge.domain.artifacts",
    "factorforge.domain.errors",
    "factorforge.domain.factors",
    "factorforge.domain.formula",
    "factorforge.domain.targets",
    "factorforge.domain.calendar",
    "factorforge.domain.monthly_signals",
)


def _read(path: Path, limit: int) -> bytes:
    """Read a caller-selected local file once, with a limit before parsing or archival."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Input limit")
        return raw
    except (OSError, ValueError):
        raise ResearchError(
            "MONTHLY_FILE_INVALID", "Monthly input is unavailable or oversized.", 422
        ) from None


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate members before a parser can choose a different declared policy."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate member")
        result[key] = value
    return result


def _constant(value: str) -> object:
    """Nonfinite JSON extensions are invalid metadata for this deterministic operation."""
    raise ValueError("Nonfinite JSON constant")


def _model[Model: BaseModel](raw: bytes, model: type[Model]) -> Model:
    """Validate bounded explicit policies in JSON mode without duplicate-member repair."""
    try:
        json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        return model.model_validate_json(raw, strict=True)
    except (ValueError, OverflowError, RecursionError):
        raise ResearchError(
            "MONTHLY_POLICY_INVALID", "Monthly policy input is invalid.", 422
        ) from None


def _save(store: ArtifactStore, value: object) -> ArtifactRef:
    """Immutable JSON references link the operation's actual inputs, results and failures."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return store.put(raw, media_type="application/json")


def _code(store: ArtifactStore) -> dict[str, object]:
    """Save installed source text without treating those snapshots as executable replay input."""
    result: dict[str, object] = {}
    try:
        for name in CODE_MODULES:
            module = importlib.import_module(name)
            if module.__file__ is None:
                raise ValueError("Installed source unavailable")
            text = _read(Path(module.__file__), 1024 * 1024).decode("utf-8")
            raw = text.replace("\r\n", "\n").encode("utf-8")
            result[name] = store.put(raw, media_type="text/x-python").model_dump(mode="json")
    except (ImportError, ValueError, OSError):
        raise ResearchError(
            "MONTHLY_CODE_UNAVAILABLE", "Installed source evidence is unavailable.", 503
        ) from None
    return result


def run_monthly_plan(
    source_path: Path,
    request_path: Path,
    portfolio_path: Path,
    store: ArtifactStore,
    *,
    missing_signal: Literal["fail", "exclude_at_formation"],
) -> dict[str, object]:
    """A fresh recorded attempt computes conditional targets and retains failed calculations."""
    if missing_signal not in ("fail", "exclude_at_formation"):
        raise ResearchError("MONTHLY_POLICY_INVALID", "Missing-signal policy is invalid.", 422)
    source_raw = _read(source_path, MAX_SOURCE_BYTES)
    request_raw = _read(request_path, 256 * 1024)
    portfolio_raw = _read(portfolio_path, 16 * 1024)
    request = _model(request_raw, MonthlySignalRequest)
    portfolio = _model(portfolio_raw, PortfolioSpec)
    if portfolio.weighting == "value_weight" and (
        request.capitalization_binding is None
        or portfolio.weight_input != request.capitalization_binding.name
    ):
        raise ResearchError(
            "MONTHLY_POLICY_INVALID", "Weight input does not match the request.", 422
        )
    try:
        environment = {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "machine": platform.machine(),
            "packages": {
                name: version(name)
                for name in ("factorforge", "pydantic", "pydantic_core", "polars")
            },
        }
    except ImportError:
        raise ResearchError(
            "MONTHLY_CODE_UNAVAILABLE", "Dependency evidence is unavailable.", 503
        ) from None
    source_ref = store.put(source_raw, media_type="application/json")
    start = _save(
        store,
        {
            "schema_version": "monthly-plan-start-v1",
            "attempt_id": str(uuid4()),
            "scope": "conditional-monthly-source-to-targets",
            "started_at": datetime.now(UTC).isoformat(),
            "source": source_ref.model_dump(mode="json"),
            "request": store.put(request_raw, media_type="application/json").model_dump(
                mode="json"
            ),
            "portfolio": store.put(portfolio_raw, media_type="application/json").model_dump(
                mode="json"
            ),
            "missing_signal": missing_signal,
            "code": _code(store),
            "text_identity": "utf8-lf-v1",
            "environment": _save(store, environment).model_dump(mode="json"),
        },
    )
    assembly_ref = None
    targets_ref = None
    error_code = None
    try:
        assembly = assemble_monthly_signals(source_ref, store, request)
        assembly_ref = store.put(assembly.canonical_bytes(), media_type="application/json")
        targets = build_targets(assembly.cross_section, portfolio, missing_signal=missing_signal)
        targets_ref = store.put(targets.canonical_bytes(), media_type="application/json")
    except ResearchError as error:
        error_code = error.code
    except Exception:
        # Unexpected calculation faults must remain visible without exposing raw data or paths.
        error_code = "MONTHLY_INTERNAL_ERROR"
    record = _save(
        store,
        {
            "schema_version": "monthly-plan-outcome-v1",
            "start": start.model_dump(mode="json"),
            "outcome": "failed" if error_code else "planned",
            "error_code": error_code,
            "finished_at": datetime.now(UTC).isoformat(),
            "assembly": assembly_ref.model_dump(mode="json") if assembly_ref else None,
            "targets": targets_ref.model_dump(mode="json") if targets_ref else None,
        },
    )
    return {
        "record": record.model_dump(mode="json"),
        "outcome": "failed" if error_code else "planned",
        "error_code": error_code,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Print an evidence pointer and use a failing exit status for unsuccessful calculations."""
    parser = argparse.ArgumentParser(
        description="Plan conditional monthly targets from saved source facts."
    )
    for name in ("source", "request", "portfolio", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--missing-signal", choices=("fail", "exclude_at_formation"), required=True)
    args = parser.parse_args(argv)
    try:
        result = run_monthly_plan(
            args.source,
            args.request,
            args.portfolio,
            LocalArtifactStore(args.output),
            missing_signal=args.missing_signal,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["outcome"] == "planned" else 1
    except ResearchError as error:
        print(
            json.dumps({"error": {"code": error.code, "message": error.message}}), file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
