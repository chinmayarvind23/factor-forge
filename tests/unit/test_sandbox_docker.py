"""Docker transport tests inspect fixed controls without pretending to run a container."""

import sys
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from factorforge.domain.errors import ResearchError
from factorforge.sandbox.docker import DockerRuntime


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
