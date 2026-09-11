"""Independent operator-boundary probes never construct a real Docker transport."""

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from uuid import UUID

import pytest

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.experiments import ExperimentSpec
from factorforge.sandbox import command


def request_bytes() -> bytes:
    """Original request metadata needs no artifact reads until runner admission."""
    return (
        ExperimentSpec(
            experiment_id=UUID(int=71),
            run_id=UUID(int=72),
            owner_issuer="factorforge-local",
            owner_subject="sandbox-cli",
            factor_spec_sha256="a" * 64,
            code=ArtifactRef(sha256="b" * 64, size_bytes=1, media_type="text/x-python"),
            config=ArtifactRef(sha256="c" * 64, size_bytes=2, media_type="application/json"),
            input_refs=(),
            seed=9,
            engine="python",
            profile="python-bounded-v2",
        )
        .model_dump_json()
        .encode()
    )


def test_denied_cli_never_reads_request_or_discovers_docker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Authorization precedes even parsing a private path or probing executable availability."""
    read = Mock(side_effect=AssertionError("request read before authorization"))
    discover = Mock(side_effect=AssertionError("binary search before authorization"))
    monkeypatch.setattr(command, "_request", read)
    monkeypatch.setattr(shutil, "which", discover)
    assert (
        command.main(["--spec", "private", "--artifact-dir", "objects", "--work-dir", "work"]) == 1
    )
    actual = capsys.readouterr()
    assert json.loads(actual.out)["failure_code"] == "SANDBOX_EXECUTION_NOT_AUTHORIZED"
    assert "private" not in actual.out + actual.err
    read.assert_not_called()
    discover.assert_not_called()


@pytest.mark.parametrize("kind", ["nested_duplicate", "string_seed", "extra_mount", "directory"])
def test_cli_strict_request_failure_precedes_runtime_and_storage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    """Nested aliases, coercion and caller controls cannot enter execution through the JSON file."""
    runtime = Mock(side_effect=AssertionError("runtime constructed for invalid request"))
    monkeypatch.setattr(command, "DockerRuntime", runtime)
    with TemporaryDirectory(prefix="factorforge-cli-review-") as temporary:
        parent = Path(temporary)
        path = parent / "request.json"
        raw = request_bytes()
        if kind == "nested_duplicate":
            raw = raw.replace(b'"size_bytes":1', b'"size_bytes":2,"size_bytes":1', 1)
        elif kind == "string_seed":
            raw = raw.replace(b'"seed":9', b'"seed":"9"')
        elif kind == "extra_mount":
            raw = raw[:-1] + b',"mount":"/private"}'
        if kind == "directory":
            path.mkdir()
        else:
            path.write_bytes(raw)
        assert (
            command.main(
                [
                    "--spec",
                    str(path),
                    "--artifact-dir",
                    str(parent / "objects"),
                    "--work-dir",
                    str(parent),
                    "--execute",
                ]
            )
            == 1
        )
        assert not (parent / "objects").exists()
        assert not list(parent.glob("docker-config-*"))
    output = capsys.readouterr()
    assert json.loads(output.out)["failure_code"] == "SANDBOX_INPUT_INVALID"
    assert temporary not in output.out + output.err
    runtime.assert_not_called()
