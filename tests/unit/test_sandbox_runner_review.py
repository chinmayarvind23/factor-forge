"""Independent lifecycle tests use fake Docker transport; no generated code runs on the host."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from typing import Any, cast
from uuid import UUID

import pytest

import factorforge.sandbox.runner as runner
from factorforge.auth.principal import LOCAL_PRINCIPAL, Principal
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.experiments import ExperimentSpec
from factorforge.sandbox.docker import PYTHON_IMAGE, DockerRuntime
from factorforge.sandbox.process import CommandResult

IDENTITY = "4" * 64
OWNER = Principal("review-issuer", "review-owner", frozenset({"execute_experiment"}))


class ReviewStore:
    """Retain exact content references and let tests fail one specific postlaunch write."""

    def __init__(self, trace: list[str]) -> None:
        """Each test owns its bytes, operation trace and optional one-shot failure."""
        self.data: dict[str, bytes] = {}
        self.trace = trace
        self.fail_output = False
        self.fail_all_writes = False

    def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Record real content identities without any filesystem or network side effect."""
        if self.fail_all_writes:
            raise ResearchError("REVIEW_STORE_FAILED", "Synthetic store failure", 503)
        if self.fail_output and media_type == "application/octet-stream":
            self.fail_output = False
            raise ResearchError("REVIEW_OUTPUT_FAILED", "Synthetic output write failure", 503)
        ref = ArtifactRef(
            sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), media_type=media_type
        )
        self.data[ref.sha256] = data
        self.trace.append("put")
        if b'"schema_version":"experiment-start-v1"' in data:
            self.trace.append("archived-start")
        if b'"operation":"staging"' in data:
            self.trace.append("archived-stage")
        return ref

    def get(self, ref: ArtifactRef) -> bytes:
        """Admission reads remain visible so denial can prove it performed no artifact access."""
        self.trace.append("get")
        data = self.data[ref.sha256]
        assert hashlib.sha256(data).hexdigest() == ref.sha256 and len(data) == ref.size_bytes
        return data


class FakeRuntime:
    """Model controller replies and container observations without invoking a real daemon."""

    def __init__(self, trace: list[str]) -> None:
        """Default behavior describes a verified completed container and confirmed removal."""
        self.trace = trace
        self.created = CommandResult(IDENTITY.encode(), b"", 0, "exited")
        self.attached = CommandResult(b"original output", b"original stderr", 0, "exited")
        self.identity: str | None = IDENTITY
        self.terminal: object = {
            "Status": "exited",
            "Running": False,
            "ExitCode": 0,
            "OOMKilled": False,
        }
        self.cleanup = True
        self.create_exception = False
        self.policy_exception = False
        self.cleanup_exception = False
        self.start_options: dict[str, Any] = {}

    def verify_seccomp(self, path: Path) -> None:
        """Record trusted preflight ordering without reading a real policy file."""
        self.trace.append("seccomp")

    def preflight(self, image: str) -> dict[str, Any]:
        """Return only the small metadata portion the orchestration consumes."""
        self.trace.append("preflight")
        return {"image": {"Id": image}, "daemon": {"review": True}}

    def create_args(self, **kwargs: Any) -> tuple[str, ...]:
        """The fake request still receives server-created nonce, staged mount and launcher."""
        self.trace.append("create-args")
        assert kwargs["image"] == PYTHON_IMAGE
        return ("create", kwargs["nonce"])

    def command(self, args: tuple[str, ...], **kwargs: Any) -> CommandResult:
        """Fixed operation replies distinguish create uncertainty from attach termination."""
        if args[0] == "create":
            self.trace.append("create")
            assert "archived-start" in self.trace
            assert "archived-stage" in self.trace
            if self.create_exception:
                raise ResearchError("SANDBOX_CONTROLLER_IO", "Synthetic controller fault", 503)
            return self.created
        if args[:3] == ("container", "start", "--attach"):
            self.trace.append("attach")
            assert "verified-created" in self.trace
            self.start_options = kwargs
            return self.attached
        assert args == ("container", "kill", IDENTITY)
        self.trace.append("kill")
        return CommandResult(b"", b"", 0, "exited")

    def find_owned(self, nonce: str) -> str | None:
        """An immediate absence observation alone cannot settle an indeterminate create."""
        self.trace.append("find-owned")
        return self.identity

    def verify_created(self, identity: str, **kwargs: Any) -> dict[str, Any]:
        """Only a verified policy permits the runner to issue start."""
        self.trace.append("verified-created")
        if self.policy_exception:
            raise ResearchError("SANDBOX_POLICY_INVALID", "Synthetic policy mismatch", 503)
        return {"Id": identity, "State": {"Status": "created"}}

    def inspect_owned(self, identity: str, nonce: str) -> dict[str, Any]:
        """Provide an independent terminal-state observation for result construction."""
        self.trace.append("inspect-owned")
        return {"Id": identity, "State": self.terminal}

    def remove_owned(self, nonce: str) -> bool:
        """Expose cleanup confirmation independently from controller or container exit."""
        self.trace.append("remove-owned")
        if self.cleanup_exception:
            raise ResearchError("SANDBOX_CONTROLLER_INVALID", "Synthetic cleanup fault", 503)
        return self.cleanup


@pytest.fixture
def setup(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]]]:
    """Original input bytes and a context-only stage keep all lifecycle tests local and bounded."""
    trace: list[str] = []
    store = ReviewStore(trace)
    request = ExperimentSpec(
        experiment_id=UUID(int=410),
        run_id=UUID(int=411),
        owner_issuer=OWNER.issuer,
        owner_subject=OWNER.subject,
        factor_spec_sha256="5" * 64,
        code=store.put(b'print("fixture")', media_type="text/x-python"),
        config=store.put(b"{}", media_type="application/json"),
        input_refs=(),
        seed=3,
        engine="python",
        profile="python-bounded-v2",
    )
    runtime = FakeRuntime(trace)
    trace.clear()

    @contextmanager
    def staged(*args: Any, **kwargs: Any) -> Iterator[Path]:
        """Record stage cleanup after the container cleanup boundary."""
        trace.append("stage")
        with TemporaryDirectory(prefix="factorforge-runner-review-") as temporary:
            try:
                yield Path(temporary)
            finally:
                gate = kwargs.get("cleanup_allowed")
                allowed = gate() if gate is not None else True
                trace.append("unstage" if allowed else "stage-kept")

    monkeypatch.setattr(runner, "staged_inputs", staged)
    yield request, store, runtime, trace


def invoke(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]],
    *,
    cancel: Event | None = None,
    principal: Principal = OWNER,
) -> dict[str, Any]:
    """Pass the fake internal transport through the real public authorization boundary."""
    request, store, runtime, _ = setup
    return runner.run_experiment(
        request,
        store,
        principal=principal,
        runtime=cast(DockerRuntime, runtime),
        parent=Path.cwd(),
        seccomp=Path.cwd() / "infra/sandbox/python-no-network-v1.json",
        cancel=cancel,
    )


@pytest.mark.parametrize(
    "reason,exit_code,oom,status,failure",
    [
        ("exited", 0, False, "completed", None),
        ("exited", 7, False, "failed", "SANDBOX_EXECUTION_FAILED"),
        ("exited", 137, True, "failed", "SANDBOX_OOM"),
        ("exited", 137, False, "failed", "SANDBOX_EXECUTION_FAILED"),
        ("timed_out", 137, False, "timed_out", "SANDBOX_TIMED_OUT"),
        ("cancelled", 137, False, "cancelled", "SANDBOX_CANCELLED"),
        ("output_limit", 137, False, "failed", "SANDBOX_OUTPUT_LIMIT"),
    ],
)
def test_lifecycle_distinguishes_controller_and_container_outcomes(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]],
    reason: str,
    exit_code: int,
    oom: bool,
    status: str,
    failure: str | None,
) -> None:
    """Timeout, cancellation, OOM and output cap preserve their distinct terminal evidence."""
    _, store, runtime, trace = setup
    runtime.attached = CommandResult(b"output", b"error", exit_code, cast(Any, reason))
    runtime.terminal = {
        "Status": "exited",
        "Running": False,
        "ExitCode": exit_code,
        "OOMKilled": oom,
    }
    result = invoke(setup)
    assert result["status"] == status and result["failure_code"] == failure
    assert result["result"]["cleanup"] == "confirmed"
    assert result["result"]["exit_code"] == exit_code and result["result"]["oom_killed"] is oom
    assert (
        trace.index("archived-start")
        < trace.index("create")
        < trace.index("verified-created")
        < trace.index("attach")
    )
    assert trace.index("remove-owned") < trace.index("unstage")
    assert ("kill" in trace) == (reason != "exited")
    assert (
        runtime.start_options["timeout"] == 30 and runtime.start_options["output_limit"] == 1048576
    )
    record = json.loads(store.get(ArtifactRef.model_validate(result["record"])))
    assert record["schema_version"] == "experiment-record-v1"
    controls = [
        json.loads(store.get(ArtifactRef.model_validate(ref))) for ref in record["controls"]
    ]
    attached = [entry for entry in controls if entry.get("operation") == "attach"]
    assert attached == [
        {
            "operation": "attach",
            "exit": exit_code,
            "reason": reason,
            "outputs": result["result"]["outputs"],
        }
    ]
    assert json.loads(store.get(ArtifactRef.model_validate(record["result"]))) == result["result"]


@pytest.mark.parametrize("raises", [False, True])
def test_unconfirmed_cleanup_overrides_success(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]], raises: bool
) -> None:
    """A zero exit cannot conceal missing cleanup confirmation, including controller errors."""
    runtime = setup[2]
    runtime.cleanup = False
    runtime.cleanup_exception = raises
    result = invoke(setup)
    assert result["status"] == "cleanup_unconfirmed"
    assert result["failure_code"] == "SANDBOX_CLEANUP_UNCONFIRMED"
    assert result["result"]["cleanup"] == "unconfirmed"


@pytest.mark.parametrize("reason", ["timed_out", "output_limit", "cancelled", "exception"])
def test_indeterminate_create_stays_unconfirmed_after_current_absence(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]], reason: str
) -> None:
    """A pending daemon create can appear after the client's healthy empty cleanup listing."""
    runtime = setup[2]
    runtime.identity = None
    if reason == "exception":
        runtime.create_exception = True
    else:
        runtime.created = CommandResult(b"", b"", None, cast(Any, reason))
    result = invoke(setup)
    assert result["status"] == "cleanup_unconfirmed"
    assert result["result"]["container_id"] is None and result["result"]["cleanup"] == "unconfirmed"
    assert "remove-owned" in setup[3] and "attach" not in setup[3]


def test_definitive_create_failure_can_confirm_absence(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]],
) -> None:
    """A completed unsuccessful create plus healthy absence needs no invented container ID."""
    runtime = setup[2]
    runtime.identity = None
    runtime.created = CommandResult(b"", b"definitive failure", 1, "exited")
    result = invoke(setup)
    assert result["status"] == "failed" and result["failure_code"] == "SANDBOX_CREATE_FAILED"
    assert result["result"]["container_id"] is None and result["result"]["cleanup"] == "confirmed"
    assert result["result"]["outputs"] == []


def test_denied_work_performs_no_read_write_stage_or_cleanup(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]],
) -> None:
    """A browser principal has no execution authority even when input references are valid."""
    with pytest.raises(ResearchError) as caught:
        invoke(setup, principal=LOCAL_PRINCIPAL)
    assert caught.value.code == "FORBIDDEN" and setup[3] == []


def test_prelaunch_cancel_archives_failure_without_touching_runtime(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]],
) -> None:
    """Cancellation before side effects retains a failed prelaunch record and no cleanup claim."""
    cancel = Event()
    cancel.set()
    result = invoke(setup, cancel=cancel)
    assert (
        result["failure_code"] == "SANDBOX_CANCELLED"
        and result["result"]["launch_attempted"] is False
    )
    assert result["result"]["cleanup"] == "not_started" and "preflight" not in setup[3]
    assert "remove-owned" not in setup[3]


def test_failed_start_archival_prevents_even_create(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]],
) -> None:
    """Without a durable nonce/start record, no controller side effect may begin."""
    setup[1].fail_all_writes = True
    with pytest.raises(ResearchError):
        invoke(setup)
    assert not any(
        operation in setup[3] for operation in ("create", "stage", "preflight", "remove-owned")
    )


@pytest.mark.parametrize("fault", ["policy", "output"])
def test_postcreate_exception_always_removes_before_unstage(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]], fault: str
) -> None:
    """Policy or artifact failures after creation still own container and stage cleanup."""
    if fault == "policy":
        setup[2].policy_exception = True
    else:
        setup[1].fail_output = True
    result = invoke(setup)
    assert result["status"] == "failed" and result["result"]["cleanup"] == "confirmed"
    assert setup[3].index("remove-owned") < setup[3].index("unstage")
    if fault == "policy":
        assert "attach" not in setup[3]


@pytest.mark.parametrize(
    "terminal",
    [
        {"Status": "exited", "Running": False, "ExitCode": True, "OOMKilled": False},
        {"Status": "exited", "Running": False, "ExitCode": -1, "OOMKilled": False},
        {"Status": "exited", "Running": False, "ExitCode": 0, "OOMKilled": "false"},
    ],
)
def test_malformed_terminal_metadata_is_archived_failure_after_cleanup(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]], terminal: dict[str, object]
) -> None:
    """Malformed daemon status must retain a failed receipt after lifecycle cleanup."""
    setup[2].terminal = terminal
    result = invoke(setup)
    assert result["status"] == "failed" and result["result"]["cleanup"] == "confirmed"
    assert result["result"]["exit_code"] is None and result["result"]["oom_killed"] is None
    assert "remove-owned" in setup[3]


@pytest.mark.parametrize("pending_create", [False, True])
def test_unconfirmed_container_cleanup_retains_staged_inputs(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]], pending_create: bool
) -> None:
    """Pending daemon operations keep their input bundle available for later reconciliation."""
    runtime = setup[2]
    if pending_create:
        runtime.created = CommandResult(b"", b"", None, "timed_out")
        runtime.identity = None
    else:
        runtime.cleanup = False
    result = invoke(setup)
    assert result["status"] == "cleanup_unconfirmed"
    assert "stage-kept" in setup[3] and "unstage" not in setup[3]


def test_cancel_after_staging_prevents_create_and_removes_stage(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The last cancellation check runs after arguments are prepared but before launch ownership."""
    cancel = Event()
    original = setup[2].create_args

    def cancelled_args(**kwargs: Any) -> tuple[str, ...]:
        """Simulate cancellation while the trusted controller prepares a staged request."""
        result = original(**kwargs)
        cancel.set()
        return result

    monkeypatch.setattr(setup[2], "create_args", cancelled_args)
    result = invoke(setup, cancel=cancel)
    assert result["failure_code"] == "SANDBOX_CANCELLED"
    assert result["result"]["launch_attempted"] is False
    assert "stage" in setup[3] and "unstage" in setup[3]
    assert "create" not in setup[3] and "remove-owned" not in setup[3]


def test_unexpected_preflight_exception_is_archived_without_cleanup(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An internal error before creation retains safe evidence without inventing container work."""

    def broken(image: str) -> dict[str, Any]:
        """Inject a non-domain exception so the general lifecycle failure path is exercised."""
        raise RuntimeError("private synthetic detail")

    monkeypatch.setattr(setup[2], "preflight", broken)
    result = invoke(setup)
    assert result["failure_code"] == "SANDBOX_INTERNAL_ERROR"
    assert result["result"]["cleanup"] == "not_started"
    assert "remove-owned" not in setup[3] and "private synthetic" not in json.dumps(result)


def test_exited_attach_with_running_container_is_not_completion(
    setup: tuple[ExperimentSpec, ReviewStore, FakeRuntime, list[str]],
) -> None:
    """A zero controller exit requires a separate terminal container observation."""
    setup[2].terminal = {"Status": "running", "Running": True, "ExitCode": 0, "OOMKilled": False}
    result = invoke(setup)
    assert result["status"] == "failed" and result["failure_code"] == "SANDBOX_EXECUTION_FAILED"
    assert result["result"]["exit_code"] is None and result["result"]["oom_killed"] is None
    assert result["result"]["cleanup"] == "confirmed"
