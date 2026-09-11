"""Experiment orchestration must authorize before Docker or staging can do work."""

from pathlib import Path
from typing import cast

import pytest
from test_experiments import OWNER, MemoryArtifacts, spec

import factorforge.sandbox.runner as module
from factorforge.auth.principal import LOCAL_PRINCIPAL
from factorforge.domain.errors import ResearchError
from factorforge.sandbox.docker import DockerRuntime
from factorforge.sandbox.runner import run_experiment


def test_denied_principal_never_touches_runtime() -> None:
    """An ordinary browser principal cannot acquire execution through the runner wrapper."""
    store = MemoryArtifacts()
    with pytest.raises(ResearchError) as error:
        run_experiment(
            spec(),
            store,
            principal=LOCAL_PRINCIPAL,
            runtime=cast(DockerRuntime, object()),
            parent=Path("."),
            seccomp=Path("."),
        )
    assert error.value.code == "FORBIDDEN" and store.reads == []


def test_busy_worker_does_not_start_another_experiment() -> None:
    """An authorized second request cannot multiply the initial worker's container budget."""
    with module._EXECUTION_LOCK, pytest.raises(ResearchError) as error:
        run_experiment(
            spec(),
            MemoryArtifacts(),
            principal=OWNER,
            runtime=cast(DockerRuntime, object()),
            parent=Path("."),
            seccomp=Path("."),
        )
    assert error.value.code == "SANDBOX_BUSY"


def test_failed_start_archival_releases_worker_slot() -> None:
    """A storage exception cannot leave the synchronous worker permanently occupied."""
    with pytest.raises(AssertionError, match="Admission must not write"):
        run_experiment(
            spec(),
            MemoryArtifacts(),
            principal=OWNER,
            runtime=cast(DockerRuntime, object()),
            parent=Path("."),
            seccomp=Path("."),
        )
    assert module._EXECUTION_LOCK.acquire(blocking=False)
    module._EXECUTION_LOCK.release()
