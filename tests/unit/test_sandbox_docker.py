"""Docker transport tests inspect fixed controls without pretending to run a container."""

import sys
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from test_sandbox_docker_review import daemon_info, image_info

from factorforge.domain.errors import ResearchError
from factorforge.sandbox.docker import PYTHON_IMAGE, DockerRuntime
from factorforge.sandbox.image_binding import PYTHON_CONFIG, PYTHON_REFERENCE


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


def test_classic_config_only_image_identity_is_unsupported(
    directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The v2 profile requires containerd manifest identity with no classic-store fallback."""
    runtime = DockerRuntime(
        binary=Path(sys.executable), endpoint="unix:///var/run/docker.sock", config=directory
    )
    actual = image_info()
    actual["Id"] = PYTHON_CONFIG
    replies = iter((daemon_info(), actual))
    calls: list[tuple[str, ...]] = []

    def response(args: tuple[str, ...], *, array: bool = False) -> dict[str, Any]:
        """Supply a classic store identity without invoking or modifying a Docker daemon."""
        calls.append(args)
        return next(replies)

    monkeypatch.setattr(runtime, "object", response)
    with pytest.raises(ResearchError) as error:
        runtime.preflight(PYTHON_IMAGE)
    assert error.value.code == "SANDBOX_IMAGE_INVALID"
    assert calls[-1] == ("image", "inspect", PYTHON_REFERENCE)
