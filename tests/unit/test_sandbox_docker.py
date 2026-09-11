"""Docker transport tests inspect fixed controls without pretending to run a container."""

import sys
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from test_sandbox_docker_review import daemon_info

from factorforge.domain.errors import ResearchError
from factorforge.sandbox.docker import PYTHON_IMAGE, DockerRuntime


@pytest.fixture
def directory() -> Iterator[Path]:
    """Avoid pytest's unsupported Windows convenience symlink without changing test assertions."""
    with TemporaryDirectory(prefix="factorforge-docker-test-") as name:
        yield Path(name)


def test_remote_endpoint_is_not_admitted(directory: Path) -> None:
    """The local worker never follows a remote daemon selected through configuration."""
    with pytest.raises(ValueError):
        DockerRuntime(
            binary=Path(sys.executable), endpoint="tcp://example.com:2375", config=directory
        )


def test_changed_seccomp_asset_fails_before_create(directory: Path) -> None:
    """An arbitrary JSON profile cannot replace the exact reviewed server-owned asset."""
    runtime = DockerRuntime(
        binary=Path(sys.executable), endpoint="unix:///var/run/docker.sock", config=directory
    )
    profile = directory / "seccomp.json"
    profile.write_bytes(b"{}")
    with pytest.raises(ResearchError) as error:
        runtime.verify_seccomp(profile)
    assert error.value.code == "SANDBOX_POLICY_INVALID"


def test_classic_image_store_preserves_manifest_and_config_id_distinction(
    directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OCI manifest and configuration digests are different pinned objects on classic Docker."""
    runtime = DockerRuntime(
        binary=Path(sys.executable), endpoint="unix:///var/run/docker.sock", config=directory
    )
    actual: dict[str, Any] = {
        "Id": "sha256:ec7d6c95cd3692a2e2d228a8b1ca74e4025b54121fcc4c5da6f09cfa473315ad",
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {"Volumes": None},
        "RepoDigests": ["python@" + PYTHON_IMAGE],
    }
    replies = iter((daemon_info(), actual))
    calls: list[tuple[str, ...]] = []

    def response(args: tuple[str, ...], *, array: bool = False) -> dict[str, Any]:
        """Supply a classic store identity without invoking or modifying a Docker daemon."""
        calls.append(args)
        return next(replies)

    monkeypatch.setattr(runtime, "object", response)
    assert runtime.preflight(PYTHON_IMAGE)["image"] == actual
    assert calls[-1] == ("image", "inspect", "python@" + PYTHON_IMAGE)
