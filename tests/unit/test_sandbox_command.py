"""Operator CLI authorization and parsing tests never start Docker implicitly."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import Mock

import pytest
from test_experiments import spec

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.errors import ResearchError
from factorforge.domain.experiments import ExperimentSpec
from factorforge.sandbox import command


def arguments(root: Path, raw: bytes | None = None) -> list[str]:
    """Build original operator-owned input with a deliberate explicit execution flag."""
    request = spec(owner_issuer="factorforge-local", owner_subject="sandbox-cli")
    source = root / "request.json"
    source.write_bytes(raw if raw is not None else request.model_dump_json().encode())
    return [
        "--spec",
        str(source),
        "--artifact-dir",
        str(root / "objects"),
        "--work-dir",
        str(root),
        "--execute",
    ]


@pytest.mark.parametrize(
    "status,exit_code", [("completed", 0), ("failed", 1), ("cleanup_unconfirmed", 1)]
)
def test_cli_forwards_validated_spec_and_explicit_operator_authority(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    exit_code: int,
) -> None:
    """Only the fixed operator identity reaches the runner, with an empty owned Docker config."""
    config_paths: list[Path] = []

    class Runtime:
        """Replace Docker construction while inspecting the real private directory lifecycle."""

        def __init__(self, *, binary: Path, endpoint: str, config: Path) -> None:
            """No child process is needed to assert fixed local transport configuration."""
            assert binary.is_absolute()
            assert endpoint in command.ENDPOINTS
            assert config.is_dir() and not list(config.iterdir())
            config_paths.append(config)

    def run(
        request: ExperimentSpec,
        store: ArtifactStore,
        *,
        principal: Principal,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """A fake terminal result keeps this test independent of actual container availability."""
        assert request.owner_subject == "sandbox-cli"
        assert principal == Principal(
            "factorforge-local", "sandbox-cli", frozenset({"execute_experiment"})
        )
        assert kwargs["parent"].is_dir()
        return {
            "record": {"sha256": "a" * 64, "size_bytes": 1, "media_type": "application/json"},
            "status": status,
            "failure_code": None if status == "completed" else "SANDBOX_TEST_FAILURE",
            "result": {"must_not_print": "private"},
        }

    monkeypatch.setattr(command, "DockerRuntime", Runtime)
    monkeypatch.setattr(command, "run_experiment", run)
    monkeypatch.setattr(shutil, "which", Mock(return_value=str(Path(sys.executable))))
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        assert command.main(arguments(root)) == exit_code
        assert all(not path.exists() for path in config_paths)
    output = json.loads(capsys.readouterr().out)
    assert set(output) == {"record", "status", "failure_code"}
    assert output["status"] == status


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b'{"seed":1,"seed":2}',
        b'{"seed":NaN}',
        b'{"seed":Infinity}',
        b"[" * 2000,
        b"\xff",
        b"x" * (2**18 + 1),
    ],
    ids=["empty", "duplicate", "nan", "infinity", "depth", "encoding", "oversized"],
)
def test_malformed_or_oversized_request_never_constructs_runtime(
    raw: bytes,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Raw parsing fails before storage creation, controller code archival or Docker calls."""
    runtime = Mock(side_effect=AssertionError("must not construct runtime"))
    monkeypatch.setattr(command, "DockerRuntime", runtime)
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        assert command.main(arguments(root, raw)) == 1
        assert not (root / "objects").exists()
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    runtime.assert_not_called()


def test_no_execute_flag_or_foreign_owner_never_constructs_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI availability cannot silently authorize a run or impersonate another owner."""
    runtime = Mock(side_effect=AssertionError("must not construct runtime"))
    monkeypatch.setattr(command, "DockerRuntime", runtime)
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        assert command.main(arguments(root)[:-1]) == 1
        assert command.main(arguments(root, spec().model_dump_json().encode())) == 1
        assert not (root / "objects").exists()
    assert len(capsys.readouterr().out.splitlines()) == 2
    runtime.assert_not_called()


def test_typed_runner_failure_is_sanitized_and_config_removed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Safe failure codes leave no transient Docker config or printed internal message."""
    monkeypatch.setattr(command, "DockerRuntime", Mock())
    monkeypatch.setattr(shutil, "which", Mock(return_value=str(Path(sys.executable))))
    monkeypatch.setattr(
        command,
        "run_experiment",
        Mock(
            side_effect=ResearchError(
                "SANDBOX_TEST_FAILURE",
                "private diagnostic",
                503,
            )
        ),
    )
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        assert command.main(arguments(root)) == 1
        assert not list(root.glob("docker-config-*"))
    output = capsys.readouterr()
    assert "private diagnostic" not in output.out + output.err
    assert json.loads(output.out)["failure_code"] == "SANDBOX_TEST_FAILURE"


def test_real_module_missing_execute_exits_without_traceback() -> None:
    """The public process boundary fails explicitly before any Docker prerequisite is needed."""
    with TemporaryDirectory() as temporary:
        args = arguments(Path(temporary))[:-1]
        child = subprocess.run(
            [sys.executable, "-m", "factorforge.sandbox.command", *args],
            capture_output=True,
            timeout=15,
            check=False,
        )
    assert child.returncode == 1
    assert json.loads(child.stdout)["failure_code"] == "SANDBOX_EXECUTION_NOT_AUTHORIZED"
    assert child.stderr == b""


@pytest.mark.parametrize(
    "extra",
    [
        ["--endpoint", "tcp://private.invalid:2375"],
        ["--image", "python:latest"],
        ["--unknown", "private"],
        ["--exec"],
    ],
)
def test_caller_transport_or_image_overrides_fail_without_runtime(
    extra: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Only server-supported local endpoints exist; image and other daemon knobs have no flag."""
    runtime = Mock()
    monkeypatch.setattr(command, "DockerRuntime", runtime)
    with TemporaryDirectory() as temporary:
        assert command.main(arguments(Path(temporary)) + extra) == 1
    output = capsys.readouterr()
    assert "private" not in output.out + output.err
    assert json.loads(output.out)["failure_code"] == "SANDBOX_CLI_ARGUMENTS"
    runtime.assert_not_called()


@pytest.mark.parametrize("found", [None, "relative-docker"])
def test_unavailable_or_relative_binary_fails_before_config_creation(
    found: str | None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Executable discovery cannot fall back to an unqualified shell command."""
    monkeypatch.setattr(shutil, "which", Mock(return_value=found))
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        assert command.main(arguments(root)) == 1
        assert not list(root.glob("docker-config-*"))
    assert json.loads(capsys.readouterr().out)["failure_code"] == "SANDBOX_CONTROLLER_UNAVAILABLE"


def test_missing_work_parent_does_not_get_created(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The operator must provision a trusted parent before the CLI stages private runtime config."""
    monkeypatch.setattr(shutil, "which", Mock(return_value=str(Path(sys.executable))))
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        argv = arguments(root)
        argv[argv.index("--work-dir") + 1] = str(root / "missing")
        assert command.main(argv) == 1
        assert not (root / "missing").exists()
    assert json.loads(capsys.readouterr().out)["failure_code"] == "SANDBOX_CONTROLLER_UNAVAILABLE"


def test_missing_spec_is_sanitized_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Read failures expose neither an absolute input path nor a raw OS exception."""
    runtime = Mock()
    monkeypatch.setattr(command, "DockerRuntime", runtime)
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        argv = arguments(root)
        (root / "request.json").unlink()
        assert command.main(argv) == 1
    output = capsys.readouterr()
    assert temporary not in output.out + output.err
    assert json.loads(output.out)["failure_code"] == "SANDBOX_INPUT_INVALID"
    runtime.assert_not_called()


def test_unexpected_runner_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An internal bug cannot print a traceback or private runtime diagnostic."""
    monkeypatch.setattr(command, "DockerRuntime", Mock())
    monkeypatch.setattr(shutil, "which", Mock(return_value=str(Path(sys.executable))))
    monkeypatch.setattr(command, "run_experiment", Mock(side_effect=RuntimeError("private secret")))
    with TemporaryDirectory() as temporary:
        assert command.main(arguments(Path(temporary))) == 1
    output = capsys.readouterr()
    assert "private secret" not in output.out + output.err
    assert json.loads(output.out)["failure_code"] == "SANDBOX_CLI_FAILED"


def test_unexpected_config_file_is_retained_and_saved_result_pointer_survives(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Cleanup never recursively removes unrecognized files or hides a completed runner receipt."""
    paths: list[Path] = []

    def runtime(**kwargs: Any) -> Mock:
        """Capture the real private config directory without invoking a daemon."""
        paths.append(kwargs["config"])
        return Mock()

    def run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        """Leave an unexpected file to force safe nonrecursive cleanup failure."""
        (paths[0] / "unexpected").write_bytes(b"keep")
        return {"record": {"sha256": "a" * 64}, "status": "completed", "failure_code": None}

    monkeypatch.setattr(command, "DockerRuntime", runtime)
    monkeypatch.setattr(shutil, "which", Mock(return_value=str(Path(sys.executable))))
    monkeypatch.setattr(command, "run_experiment", run)
    with TemporaryDirectory() as temporary:
        assert command.main(arguments(Path(temporary))) == 1
        assert (paths[0] / "unexpected").read_bytes() == b"keep"
    result = json.loads(capsys.readouterr().out)
    assert result["record"]["sha256"] == "a" * 64
    assert result["failure_code"] == "SANDBOX_STAGING_CLEANUP"
