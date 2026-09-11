"""Independent command probes check archive order, complete replay and failure boundaries."""

import importlib
import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

import pytest
from test_monthly_command import inputs

import factorforge.factors.monthly_command as command
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.monthly_signals import MAX_SOURCE_BYTES, assemble_monthly_signals
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import PortfolioSpec
from factorforge.domain.monthly_signals import MonthlySignalRequest
from factorforge.domain.targets import TargetPlan
from factorforge.factors.targets import build_targets


class ObservedStore(LocalArtifactStore):
    """A real content store records saved schemas and permits a narrow terminal-write fault."""

    def __init__(self, root: Path, *, reject_outcome: bool = False) -> None:
        """The injected fault does not alter reads or earlier durable artifact writes."""
        super().__init__(root)
        self.documents: list[tuple[dict[str, Any], ArtifactRef]] = []
        self.reject_outcome = reject_outcome

    def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Only a terminal-record write can fail; all other objects use the actual store."""
        value = json.loads(data) if media_type == "application/json" else None
        if (
            isinstance(value, dict)
            and value.get("schema_version") == "monthly-plan-outcome-v1"
            and self.reject_outcome
        ):
            raise ResearchError("ARTIFACT_WRITE_TEST", "Owned injected storage failure.", 503)
        reference = super().put(data, media_type=media_type)
        if isinstance(value, dict):
            self.documents.append((value, reference))
        return reference


def saved(store: LocalArtifactStore, pointer: object) -> dict[str, Any]:
    """A saved JSON record is always read through its validated artifact reference."""
    value: dict[str, Any] = json.loads(store.get(ArtifactRef.model_validate(pointer)))
    return value


def assert_reference_closure(store: LocalArtifactStore, value: object) -> None:
    """Verify every nested structured reference without executing any archived code."""
    if isinstance(value, dict):
        if set(value) == {"sha256", "size_bytes", "media_type"}:
            reference = ArtifactRef.model_validate(value)
            raw = store.get(reference)
            if reference.media_type == "application/json":
                assert_reference_closure(store, json.loads(raw))
        else:
            for child in value.values():
                assert_reference_closure(store, child)
    elif isinstance(value, list):
        for child in value:
            assert_reference_closure(store, child)


def test_archived_inputs_recompute_exact_targets_after_original_files_are_deleted() -> None:
    """Replay uses verified data with installed trusted code and never executes code artifacts."""
    with TemporaryDirectory(prefix="ff-monthly-replay-review-") as directory:
        root = Path(directory)
        paths = inputs(root)
        store = LocalArtifactStore(root / "objects")
        result = command.run_monthly_plan(*paths, store, missing_signal="fail")
        record = saved(store, result["record"])
        start = saved(store, record["start"])
        assert_reference_closure(store, record)
        for path in paths:
            path.unlink()
        query = MonthlySignalRequest.model_validate_json(
            store.get(ArtifactRef.model_validate(start["request"])), strict=True
        )
        policy = PortfolioSpec.model_validate_json(
            store.get(ArtifactRef.model_validate(start["portfolio"])), strict=True
        )
        assembly = assemble_monthly_signals(
            ArtifactRef.model_validate(start["source"]), store, query
        )
        target = build_targets(assembly.cross_section, policy, missing_signal="fail")
        original = TargetPlan.model_validate_json(
            store.get(ArtifactRef.model_validate(record["targets"])), strict=True
        )
        assert target == original
        assert assembly.canonical_bytes() == store.get(
            ArtifactRef.model_validate(record["assembly"])
        )
        assert set(saved(store, start["environment"])["packages"]) >= {
            "factorforge",
            "pydantic",
            "polars",
        }
        environment = saved(store, start["environment"])
        assert environment["system"] and environment["machine"]


def test_start_and_complete_code_environment_are_stored_before_any_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first economic operation observes an already verified start and dependency closure."""
    with TemporaryDirectory(prefix="ff-monthly-start-review-") as directory:
        root = Path(directory)
        store = ObservedStore(root / "objects")
        original = assemble_monthly_signals

        def checked(*args: Any, **kwargs: Any) -> Any:
            """Verify chronology at the exact first calculation boundary."""
            starts = [
                document
                for document, _ in store.documents
                if document.get("schema_version") == "monthly-plan-start-v1"
            ]
            assert len(starts) == 1
            assert_reference_closure(store, starts[0])
            return original(*args, **kwargs)

        monkeypatch.setattr(command, "assemble_monthly_signals", checked)
        assert (
            command.run_monthly_plan(*inputs(root), store, missing_signal="fail")["outcome"]
            == "planned"
        )


@pytest.mark.parametrize("kind", ["typed", "unexpected"])
def test_calculation_fault_retains_safe_failed_outcome(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """An unsuccessful calculation remains visible without serializing private exception text."""
    with TemporaryDirectory(prefix="ff-monthly-fault-review-") as directory:
        root = Path(directory)
        store = ObservedStore(root / "objects")

        def failure(*args: object, **kwargs: object) -> None:
            """Inject an owned deterministic fault after admission and archival."""
            if kind == "typed":
                raise ResearchError("OWNED_TEST_FAILURE", "DO_NOT_PUBLISH_TEST_DETAIL", 422)
            raise RuntimeError("DO_NOT_PUBLISH_TEST_DETAIL")

        monkeypatch.setattr(command, "assemble_monthly_signals", failure)
        result = command.run_monthly_plan(*inputs(root), store, missing_signal="fail")
        record = saved(store, result["record"])
        assert record["outcome"] == "failed"
        assert record["error_code"] == (
            "OWNED_TEST_FAILURE" if kind == "typed" else "MONTHLY_INTERNAL_ERROR"
        )
        assert record["assembly"] is None and record["targets"] is None
        assert "DO_NOT_PUBLISH_TEST_DETAIL" not in json.dumps(record)
        assert_reference_closure(store, record)


def test_terminal_storage_failure_leaves_start_without_a_false_complete_outcome() -> None:
    """A failed final write is an incomplete operation, even if calculation artifacts exist."""
    with TemporaryDirectory(prefix="ff-monthly-storage-review-") as directory:
        root = Path(directory)
        store = ObservedStore(root / "objects", reject_outcome=True)
        with pytest.raises(ResearchError) as caught:
            command.run_monthly_plan(*inputs(root), store, missing_signal="fail")
        assert caught.value.code == "ARTIFACT_WRITE_TEST"
        starts = [
            (document, ref)
            for document, ref in store.documents
            if document.get("schema_version") == "monthly-plan-start-v1"
        ]
        assert len(starts) == 1
        assert_reference_closure(store, starts[0][0])
        assert not any(
            document.get("schema_version") == "monthly-plan-outcome-v1"
            for document, _ in store.documents
        )


def test_malformed_source_is_retained_as_failed_after_start() -> None:
    """Raw source parse failures belong to the calculation denominator after byte admission."""
    with TemporaryDirectory(prefix="ff-monthly-malformed-review-") as directory:
        root = Path(directory)
        paths = inputs(root)
        paths[0].write_bytes(b'{"facts":[')
        store = LocalArtifactStore(root / "objects")
        result = command.run_monthly_plan(*paths, store, missing_signal="fail")
        record = saved(store, result["record"])
        assert record["error_code"] == "MONTHLY_SOURCE_INVALID"
        assert saved(store, record["start"])["source"]["size_bytes"] == len(b'{"facts":[')


@pytest.mark.parametrize("case", ["missing_cap", "different_cap", "oversized", "missing_file"])
def test_inadmissible_file_or_weight_policy_never_creates_a_start(case: str) -> None:
    """Source byte limits and required value-weight bindings precede operation admission."""
    with TemporaryDirectory(prefix="ff-monthly-policy-review-") as directory:
        root = Path(directory)
        paths = inputs(root)
        if case in {"missing_cap", "different_cap"}:
            portfolio = json.loads(paths[2].read_bytes())
            portfolio.update(weighting="value_weight", weight_input="market_cap")
            paths[2].write_text(json.dumps(portfolio), encoding="utf-8")
            if case == "different_cap":
                query = json.loads(paths[1].read_bytes())
                query["capitalization_binding"] = dict(
                    name="another_cap",
                    concept="cap",
                    unit="USD",
                    history_observations=1,
                    frequency="monthly",
                    period_context="instant",
                )
                paths[1].write_text(json.dumps(query), encoding="utf-8")
        elif case == "oversized":
            paths[0].write_bytes(b" " * (MAX_SOURCE_BYTES + 1))
        else:
            paths[0].unlink()
        store = ObservedStore(root / "objects")
        with pytest.raises(ResearchError):
            command.run_monthly_plan(*paths, store, missing_signal="fail")
        assert store.documents == []


@pytest.mark.parametrize("missing", [False, True])
def test_real_module_cli_returns_correct_exit_status_and_verified_pointer(missing: bool) -> None:
    """A real Python process prints JSON evidence for both planned and failed calculations."""
    with TemporaryDirectory(prefix="ff-monthly-cli-review-") as directory:
        root = Path(directory)
        paths = inputs(root, missing=missing)
        args = [
            sys.executable,
            "-m",
            "factorforge.factors.monthly_command",
            "--source",
            str(paths[0]),
            "--request",
            str(paths[1]),
            "--portfolio",
            str(paths[2]),
            "--output",
            str(root / "objects"),
            "--missing-signal",
            "fail",
        ]
        process = subprocess.run(args, check=False, capture_output=True, text=True, timeout=30)
        assert process.returncode == (1 if missing else 0), process.stderr
        result = json.loads(process.stdout)
        assert result["outcome"] == ("failed" if missing else "planned")
        assert bool(result["error_code"]) is missing
        assert_reference_closure(LocalArtifactStore(root / "objects"), result["record"])


def test_explicit_reruns_have_distinct_starts_but_identical_targets() -> None:
    """A new attempt records another denominator entry without changing deterministic targets."""
    with TemporaryDirectory(prefix="ff-monthly-rerun-review-") as directory:
        root = Path(directory)
        paths = inputs(root)
        store = LocalArtifactStore(root / "objects")
        records = [
            saved(store, command.run_monthly_plan(*paths, store, missing_signal="fail")["record"])
            for _ in range(2)
        ]
        assert records[0]["start"] != records[1]["start"]
        assert records[0]["targets"] == records[1]["targets"]


@pytest.mark.parametrize("case", ["missing_module_path", "invalid_source_text", "missing_package"])
def test_incomplete_installed_lineage_blocks_before_calculation(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Missing installed source or dependency evidence prevents an unqualified target result."""
    with TemporaryDirectory(prefix="ff-monthly-lineage-review-") as directory:
        root = Path(directory)
        paths = inputs(root)
        store = ObservedStore(root / "objects")
        if case == "missing_package":

            def missing(name: str) -> str:
                """The environment snapshot cannot pretend an absent package version exists."""
                raise PackageNotFoundError("owned-test-package")

            monkeypatch.setattr(command, "version", missing)
        else:
            bad = root / "owned-invalid-source.py"
            bad.write_bytes(b"\xff")
            original = importlib.import_module

            def module(name: str) -> Any:
                """Only the tested module exposes a deliberately unavailable source path."""
                if name == "factorforge.factors.monthly_command":
                    return SimpleNamespace(
                        __file__=None if case == "missing_module_path" else str(bad)
                    )
                return original(name)

            monkeypatch.setattr(importlib, "import_module", module)
        with pytest.raises(ResearchError) as caught:
            command.run_monthly_plan(*paths, store, missing_signal="fail")
        assert caught.value.code == "MONTHLY_CODE_UNAVAILABLE"
        assert not any(
            document.get("schema_version") == "monthly-plan-start-v1"
            for document, _ in store.documents
        )


@pytest.mark.parametrize("case", ["invalid_missing_policy", "nonfinite_policy"])
def test_invalid_cli_policy_is_rejected_without_a_started_attempt(case: str) -> None:
    """Nonfinite metadata and unsupported missing-data rules are admission errors."""
    with TemporaryDirectory(prefix="ff-monthly-admission-review-") as directory:
        root = Path(directory)
        paths = inputs(root)
        policy: Any = "invented" if case == "invalid_missing_policy" else "fail"
        if case == "nonfinite_policy":
            paths[2].write_bytes(b'{"bucket_count":NaN}')
        store = ObservedStore(root / "objects")
        with pytest.raises(ResearchError) as caught:
            command.run_monthly_plan(*paths, store, missing_signal=policy)
        assert caught.value.code == "MONTHLY_POLICY_INVALID"
        assert store.documents == []


def test_real_cli_admission_error_uses_safe_stderr_and_nonzero_exit() -> None:
    """Unavailable source files produce typed JSON errors without exposing caller paths."""
    with TemporaryDirectory(prefix="ff-monthly-cli-invalid-review-") as directory:
        root = Path(directory)
        paths = inputs(root)
        paths[0].unlink()
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "factorforge.factors.monthly_command",
                "--source",
                str(paths[0]),
                "--request",
                str(paths[1]),
                "--portfolio",
                str(paths[2]),
                "--output",
                str(root / "objects"),
                "--missing-signal",
                "fail",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert process.returncode == 1 and process.stdout == ""
        assert json.loads(process.stderr)["error"]["code"] == "MONTHLY_FILE_INVALID"
        assert str(root) not in process.stderr
