"""A runnable monthly plan preserves verified inputs and unsuccessful calculations."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.factors.monthly_command import run_monthly_plan


def inputs(directory: Path, *, missing: bool = False) -> tuple[Path, Path, Path]:
    """Two original securities make the expected unit long/short allocation transparent."""
    source = {
        "schema_version": "monthly-source-v1",
        "facts": [
            dict(
                security_id=security,
                concept="score",
                period_end="2024-04-30",
                value=value,
                unit="dimensionless",
                available_at="2024-04-30T20:00:00Z",
                source_id="original",
                revision=0,
            )
            for security, value in (("A", "1"), ("B", "2"))
            if not (missing and security == "B")
        ],
        "membership": [
            dict(
                security_id=security,
                event_id="entry",
                included=True,
                effective_at="2024-04-01T00:00:00Z",
                available_at="2024-04-01T00:00:00Z",
            )
            for security in ("A", "B")
        ],
    }
    request = {
        "formation": dict(
            calendar_sha256="a" * 64,
            formation_at="2024-04-30T20:00:00Z",
            trade_at="2024-05-01T13:30:00Z",
        ),
        "formula": "score",
        "formation_lag_months": 0,
        "bindings": [
            dict(
                name="score",
                concept="score",
                unit="dimensionless",
                history_observations=1,
                frequency="monthly",
                period_context="instant",
            )
        ],
        "capitalization_binding": None,
        "freshness": "explicit_requested_calendar_month_no_stale_fallback_v1",
        "revision_policy": "latest_available_then_revision_reject_conflicts",
    }
    portfolio = dict(
        direction="long_high_short_low",
        bucket_count=2,
        bucket_allocation="balanced_contiguous_low_remainder",
        weighting="equal_weight",
        weight_input=None,
        breakpoints="all_eligible",
        ties="stable_security_id",
        minimum_bucket_size=1,
        long_exposure=1,
        short_exposure=1,
        sizing_basis="pre_trade_nav",
        short_proceeds="segregated",
        cash_return="zero",
    )
    paths = tuple(directory / name for name in ("source.json", "request.json", "portfolio.json"))
    for path, payload in zip(paths, (source, request, portfolio), strict=True):
        path.write_text(json.dumps(payload), encoding="utf-8")
    return paths[0], paths[1], paths[2]


def read(store: LocalArtifactStore, ref: Any) -> dict[str, Any]:
    """Read each saved component through the same hash-verifying artifact boundary."""
    value: dict[str, Any] = json.loads(store.get(ArtifactRef.model_validate(ref)))
    return value


def test_command_preserves_source_to_target_inputs_and_results() -> None:
    """The output names actual stored inputs, source evidence and exact unit weights."""
    with TemporaryDirectory(prefix="ff-monthly-command-") as directory:
        root = Path(directory)
        paths = inputs(root)
        store = LocalArtifactStore(root / "objects")
        result = run_monthly_plan(*paths, store, missing_signal="fail")
        record = read(store, result["record"])
        assert record["outcome"] == "planned"
        start = read(store, record["start"])
        assert start["scope"] == "conditional-monthly-source-to-targets"
        assert len(start["code"]) >= 10
        for reference in start["code"].values():
            assert store.get(ArtifactRef.model_validate(reference))
        for name, path in zip(("source", "request", "portfolio"), paths, strict=True):
            assert store.get(ArtifactRef.model_validate(start[name])) == path.read_bytes()
            path.unlink()
        assert read(store, start["source"])["facts"][1]["value"] == "2"
        targets = read(store, record["targets"])
        assert [row["weight"]["numerator"] for row in targets["positions"]] == ["-1", "1"]
        assert read(store, record["assembly"])["source_ref"] == start["source"]


def test_failed_target_construction_retains_the_start_and_assembly() -> None:
    """A missing required signal cannot disappear from the archived operation outcome."""
    with TemporaryDirectory(prefix="ff-monthly-failure-") as directory:
        root = Path(directory)
        store = LocalArtifactStore(root / "objects")
        result = run_monthly_plan(*inputs(root, missing=True), store, missing_signal="fail")
        record = read(store, result["record"])
        assert record["outcome"] == "failed"
        assert record["error_code"]
        assert record["targets"] is None
        assert read(store, record["start"])["missing_signal"] == "fail"
        assert read(store, record["assembly"])["cross_section"]["observations"][1]["signal"] is None


def test_invalid_policy_fails_before_any_operation_start() -> None:
    """An invalid declared policy is an input error, not a completed planning attempt."""
    with TemporaryDirectory(prefix="ff-monthly-invalid-") as directory:
        root = Path(directory)
        paths = inputs(root)
        paths[2].write_text('{"bucket_count":2,"bucket_count":3}', encoding="utf-8")
        with pytest.raises(ResearchError):
            run_monthly_plan(*paths, LocalArtifactStore(root / "objects"), missing_signal="fail")
