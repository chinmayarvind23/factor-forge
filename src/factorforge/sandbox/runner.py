"""Archive bounded local Python experiments; process output is never quant validation."""

import importlib
import json
import platform
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from threading import Event, Lock
from typing import Any
from uuid import uuid4

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.experiments import ExperimentAdmission, ExperimentResult, ExperimentSpec
from factorforge.sandbox.docker import PYTHON_IMAGE, DockerRuntime
from factorforge.sandbox.policy import admit_experiment
from factorforge.sandbox.staging import staged_inputs

CODE_MODULES = (
    "factorforge",
    "factorforge.sandbox.runner",
    "factorforge.sandbox.docker",
    "factorforge.sandbox.staging",
    "factorforge.sandbox.process",
    "factorforge.sandbox.policy",
    "factorforge.auth.principal",
    "factorforge.data.artifacts",
    "factorforge.domain.artifacts",
    "factorforge.domain.errors",
    "factorforge.domain.experiments",
    "factorforge.domain.factors",
    "factorforge.domain.formula",
)
_EXECUTION_LOCK = Lock()


def _save(store: ArtifactStore, value: object) -> ArtifactRef:
    """Canonical JSON links immutable controller metadata without executing returned content."""
    return store.put(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"),
        media_type="application/json",
    )


def _code(store: ArtifactStore) -> dict[str, Any]:
    """Record installed controller source identities before side effects; snapshots are evidence."""
    result: dict[str, Any] = {}
    for name in CODE_MODULES:
        module = importlib.import_module(name)
        if module.__file__ is None:
            raise ResearchError(
                "SANDBOX_CODE_UNAVAILABLE", "Controller source is unavailable.", 503
            )
        with Path(module.__file__).open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ResearchError("SANDBOX_CODE_UNAVAILABLE", "Controller source is oversized.", 503)
        result[name] = store.put(
            raw.replace(b"\r\n", b"\n"), media_type="text/x-python"
        ).model_dump(mode="json")
    return result


def _launcher(spec: ExperimentSpec) -> str:
    """Verify mounted bytes before execution and seed the stdlib; paths never come from code."""
    expected = {
        "code.py": (spec.code.size_bytes, spec.code.sha256),
        "config.json": (spec.config.size_bytes, spec.config.sha256),
    }
    expected.update(
        {"inputs/" + ref.sha256: (ref.size_bytes, ref.sha256) for ref in spec.input_refs}
    )
    # -B -s -P preserve PYTHONHASHSEED; isolated mode (-I) would silently ignore it.
    return (
        "import hashlib,pathlib,random,runpy\n"
        f"expected={expected!r}\n"
        "for name,(size,digest) in expected.items():\n"
        " with (pathlib.Path('/input')/name).open('rb') as stream: data=stream.read(size+1)\n"
        " if len(data)!=size or hashlib.sha256(data).hexdigest()!=digest:\n"
        "  raise RuntimeError('INPUT_INTEGRITY')\n"
        f"random.seed({spec.seed})\n"
        "runpy.run_path('/input/code.py',run_name='__main__')\n"
    )


def run_experiment(
    spec: ExperimentSpec,
    store: ArtifactStore,
    *,
    principal: Principal,
    runtime: DockerRuntime,
    parent: Path,
    seccomp: Path,
    cancel: Event | None = None,
) -> dict[str, Any]:
    """Authorize, stage, inspect, execute and remove one owned container with immutable receipts.

    Run/FactorSpec ownership resolution remains the trusted caller's responsibility. A controller
    crash leaves the saved nonce/start for reconciliation; this synchronous API has no daemon-wide
    janitor. Admission never makes a browser principal execution-capable. No expensive retry occurs.
    """
    admission = admit_experiment(
        spec,
        store,
        principal=principal,
        image_digest=PYTHON_IMAGE,
        allowed_image_digests=frozenset({PYTHON_IMAGE}),
    )
    if not _EXECUTION_LOCK.acquire(blocking=False):
        raise ResearchError("SANDBOX_BUSY", "This worker already has an active experiment.", 409)
    try:
        return _run_admitted(
            admission, store, runtime=runtime, parent=parent, seccomp=seccomp, cancel=cancel
        )
    finally:
        _EXECUTION_LOCK.release()


def _run_admitted(
    admission: ExperimentAdmission,
    store: ArtifactStore,
    *,
    runtime: DockerRuntime,
    parent: Path,
    seccomp: Path,
    cancel: Event | None,
) -> dict[str, Any]:
    """One active experiment per worker keeps resource budgets and cleanup receipts exclusive."""
    request = admission.spec
    nonce = uuid4().hex
    start_ref = _save(
        store,
        {
            "schema_version": "experiment-start-v1",
            "nonce": nonce,
            "created_at": datetime.now(UTC).isoformat(),
            "admission": admission.model_dump(mode="json"),
            "code": _code(store),
            "environment": {
                "python": platform.python_version(),
                "system": platform.system(),
                "machine": platform.machine(),
                "packages": {
                    name: version(name) for name in ("factorforge", "pydantic", "pydantic_core")
                },
            },
        },
    )
    state: dict[str, Any] = {
        "spec": request,
        "policy": admission.policy,
        "image_digest": PYTHON_IMAGE,
        "status": "failed",
        "launch_attempted": False,
        "container_id": None,
        "started_at": None,
        "exit_code": None,
        "oom_killed": None,
        "cleanup": "not_started",
        "outputs": (),
        "failure_code": "SANDBOX_PRELAUNCH_FAILED",
    }
    controls: list[ArtifactRef] = []
    uncertain_create = False
    try:
        if cancel is not None and cancel.is_set():
            raise ResearchError("SANDBOX_CANCELLED", "Experiment was cancelled before launch.", 409)
        runtime.verify_seccomp(seccomp)
        controls.append(store.put(seccomp.read_bytes(), media_type="application/json"))
        actual = runtime.preflight(PYTHON_IMAGE)
        controls.append(_save(store, actual))
        launcher = _launcher(request)
        with staged_inputs(
            admission,
            store,
            parent=parent,
            cleanup_allowed=lambda: state["cleanup"] != "unconfirmed",
        ) as mount:
            controls.append(
                _save(
                    store,
                    {
                        "operation": "staging",
                        "nonce": nonce,
                        "mount": str(mount),
                        "start": start_ref.model_dump(mode="json"),
                    },
                )
            )
            args = runtime.create_args(
                nonce=nonce,
                mount=mount,
                seccomp=seccomp,
                image=PYTHON_IMAGE,
                seed=request.seed,
                launcher=launcher,
            )
            if cancel is not None and cancel.is_set():
                raise ResearchError(
                    "SANDBOX_CANCELLED", "Experiment was cancelled before launch.", 409
                )
            state.update(launch_attempted=True, started_at=datetime.now(UTC), cleanup="unconfirmed")
            try:
                # A killed create client can leave a still-pending daemon create. Absence alone
                # cannot prove that no container will appear after an indeterminate create.
                uncertain_create = True
                created = runtime.command(args)
                uncertain_create = created.reason != "exited"
                controls.append(
                    _save(
                        store,
                        {
                            "operation": "create",
                            "exit": created.returncode,
                            "reason": created.reason,
                            "stdout": created.stdout.decode("utf-8", "replace"),
                            "stderr": created.stderr.decode("utf-8", "replace"),
                        },
                    )
                )
                identity = runtime.find_owned(nonce)
                state["container_id"] = identity
                if identity is None or created.reason != "exited" or created.returncode != 0:
                    raise ResearchError("SANDBOX_CREATE_FAILED", "Experiment creation failed.", 503)
                uncertain_create = False
                controls.append(
                    _save(
                        store,
                        runtime.verify_created(
                            identity,
                            nonce=nonce,
                            mount=mount,
                            seccomp=seccomp,
                            image=actual["image"],
                            seed=request.seed,
                            launcher=launcher,
                        ),
                    )
                )
                response = runtime.command(
                    ("container", "start", "--attach", identity),
                    timeout=30,
                    output_limit=1048576,
                    cancel=cancel,
                )
                state["outputs"] = (
                    store.put(response.stdout, media_type="application/octet-stream"),
                    store.put(response.stderr, media_type="application/octet-stream"),
                )
                if response.reason != "exited":
                    runtime.inspect_owned(identity, nonce)
                    runtime.command(("container", "kill", identity))
                observed = runtime.inspect_owned(identity, nonce)
                controls.append(_save(store, observed))
                terminal = observed.get("State", {})
                if (
                    terminal.get("Status") in {"exited", "dead"}
                    and terminal.get("Running") is False
                ):
                    if (
                        type(terminal.get("ExitCode")) is not int
                        or not 0 <= terminal["ExitCode"] <= 255
                        or type(terminal.get("OOMKilled")) is not bool
                    ):
                        raise ResearchError(
                            "SANDBOX_TERMINAL_INVALID",
                            "Container terminal evidence is invalid.",
                            503,
                        )
                    state.update(
                        exit_code=terminal.get("ExitCode"), oom_killed=terminal.get("OOMKilled")
                    )
                if response.reason in {"timed_out", "cancelled"}:
                    state.update(
                        status=response.reason, failure_code="SANDBOX_" + response.reason.upper()
                    )
                elif response.reason == "output_limit":
                    state["failure_code"] = "SANDBOX_OUTPUT_LIMIT"
                elif (
                    response.returncode == 0
                    and state["exit_code"] == 0
                    and state["oom_killed"] is False
                ):
                    state.update(status="completed", failure_code=None)
                else:
                    state["failure_code"] = (
                        "SANDBOX_OOM" if state["oom_killed"] else "SANDBOX_EXECUTION_FAILED"
                    )
            finally:
                confirmed = runtime.remove_owned(nonce)
                state["cleanup"] = (
                    "confirmed" if confirmed and not uncertain_create else "unconfirmed"
                )
                controls.append(
                    _save(
                        store,
                        {
                            "operation": "cleanup",
                            "responses": getattr(runtime, "cleanup_evidence", []),
                        },
                    )
                )
    except ResearchError as error:
        state.update(status="failed", failure_code=error.code)
    except Exception:
        # Preserve an internal failure as data; the inner finally still owns container cleanup.
        state.update(status="failed", failure_code="SANDBOX_INTERNAL_ERROR")
    if state["cleanup"] == "unconfirmed":
        state.update(status="cleanup_unconfirmed", failure_code="SANDBOX_CLEANUP_UNCONFIRMED")
    state["finished_at"] = datetime.now(UTC)
    result = ExperimentResult.model_validate(state)
    result_ref = store.put(result.canonical_bytes(), media_type="application/json")
    record = {
        "schema_version": "experiment-record-v1",
        "start": start_ref.model_dump(mode="json"),
        "result": result_ref.model_dump(mode="json"),
        "controls": [ref.model_dump(mode="json") for ref in controls],
    }
    record_ref = _save(store, record)
    return {
        "record": record_ref.model_dump(mode="json"),
        "status": result.status,
        "failure_code": result.failure_code,
        "result": result.model_dump(mode="json"),
    }
