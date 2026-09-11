"""Explicit real-daemon acceptance is required separately from ordinary unit execution."""

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from threading import Event, Timer
from uuid import uuid4

import pytest

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.experiments import ExperimentSpec
from factorforge.sandbox.docker import DockerRuntime
from factorforge.sandbox.runner import run_experiment

pytestmark = pytest.mark.skipif(
    os.getenv("FACTORFORGE_SANDBOX_ACCEPTANCE") != "1",
    reason="Real sandbox acceptance requires an explicitly selected local daemon",
)
ROOT = Path(__file__).resolve().parents[2]


def verify_closure(store: LocalArtifactStore, reference: ArtifactRef) -> dict[str, bytes]:
    """Independently traverse every saved reference and recompute raw byte lengths and hashes."""
    pending = [reference.model_dump(mode="json")]
    objects: dict[str, bytes] = {}
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if set(value) == {"sha256", "size_bytes", "media_type"}:
                ref = ArtifactRef.model_validate(value)
                raw = store.get(ref)
                assert len(raw) == ref.size_bytes and hashlib.sha256(raw).hexdigest() == ref.sha256
                if ref.sha256 not in objects:
                    objects[ref.sha256] = raw
                    if ref.media_type == "application/json":
                        pending.append(json.loads(raw))
            else:
                pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return objects


@pytest.mark.parametrize(
    "case", ["arithmetic", "isolation", "pids", "oom", "output", "timeout", "cancel", "child"]
)
def test_real_bounded_container(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Retain original bounded diagnostics and their artifacts even when assertions fail."""
    binary = shutil.which("docker")
    assert binary is not None, "Required sandbox daemon is unavailable"
    endpoint = os.environ["FACTORFORGE_SANDBOX_ENDPOINT"]
    evidence = Path(os.environ["FACTORFORGE_SANDBOX_EVIDENCE"]).absolute() / (
        case + "-" + uuid4().hex
    )
    evidence.mkdir(parents=True)
    work = evidence / "work"
    config = work / "docker-config"
    config.mkdir(parents=True)
    canary = work / "host-canary.txt"
    original_canary = b"Original nonsecret host canary"
    canary.write_bytes(original_canary)
    monkeypatch.setenv("FACTORFORGE_HOST_ONLY", "Original nonsecret environment canary")
    store = LocalArtifactStore(evidence / "objects")
    source = (
        ROOT / "tests/fixtures/sandbox" / (("timeout" if case == "cancel" else case) + ".py")
    ).read_bytes()
    owner = Principal("factorforge-local", "sandbox-acceptance", frozenset({"execute_experiment"}))
    request = ExperimentSpec(
        experiment_id=uuid4(),
        run_id=uuid4(),
        owner_issuer=owner.issuer,
        owner_subject=owner.subject,
        factor_spec_sha256="a" * 64,
        code=store.put(source, media_type="text/x-python"),
        config=store.put(b"{}", media_type="application/json"),
        input_refs=(),
        seed=7,
        engine="python",
        profile="python-bounded-v1",
    )
    runtime = DockerRuntime(binary=Path(binary), endpoint=endpoint, config=config)
    cancel = Event()
    timer = Timer(4, cancel.set) if case == "cancel" else None
    if timer is not None:
        timer.start()
    started = time.monotonic()
    try:
        receipt = run_experiment(
            request,
            store,
            principal=owner,
            runtime=runtime,
            parent=work,
            seccomp=ROOT / "infra/sandbox/python-no-network-v1.json",
            cancel=cancel,
        )
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
    receipt["acceptance_case"] = case
    receipt["wall_seconds"] = time.monotonic() - started
    receipt["host_canary_before"] = store.put(original_canary).model_dump(mode="json")
    receipt["host_canary_after"] = store.put(canary.read_bytes()).model_dump(mode="json")
    (evidence / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    result = receipt["result"]
    expected_status = {
        "oom": "failed",
        "output": "failed",
        "timeout": "timed_out",
        "cancel": "cancelled",
    }.get(case, "completed")
    assert receipt["status"] == expected_status, receipt["failure_code"]
    assert result["cleanup"] == "confirmed" and result["launch_attempted"] is True
    assert receipt["host_canary_before"] == receipt["host_canary_after"]
    objects = verify_closure(store, ArtifactRef.model_validate(receipt["record"]))
    assert objects[request.code.sha256] == source
    stdout = store.get(ArtifactRef.model_validate(result["outputs"][0]))
    stderr = store.get(ArtifactRef.model_validate(result["outputs"][1]))
    assert len(stdout) + len(stderr) <= 1048576
    controls = json.loads(objects[receipt["record"]["sha256"]])["controls"]
    cleanup = [
        json.loads(objects[ref["sha256"]])
        for ref in controls
        if json.loads(objects[ref["sha256"]]).get("operation") == "cleanup"
    ]
    assert len(cleanup) == 1 and len(cleanup[0]["responses"]) == 4
    responses = cleanup[0]["responses"]
    assert responses[2]["argv"] == ["container", "rm", "--force", result["container_id"]]
    assert responses[-1]["reason"] == "exited" and responses[-1]["exit"] == 0
    assert responses[-1]["stdout"] == ""
    if case == "arithmetic":
        assert json.loads(stdout) == {"sum": 5050, "seeded": 0.32383276483316237}
    elif case == "isolation":
        actual = json.loads(stdout)
        assert actual["uid"] == actual["gid"] == 65532
        assert actual["capabilities"] == "0000000000000000"
        assert actual["seccomp"] == "2" and actual["no_new_privileges"] == "1"
        assert all(
            actual[key] is True
            for key in (
                "root_write_denied",
                "input_write_denied",
                "canary_not_mounted",
                "host_env_absent",
            )
        )
        assert all(actual["socket_denials"].values()) and len(actual["socket_denials"]) == 5
        assert actual["cgroups"] == {
            "cpu.max": "100000 100000",
            "memory.max": "536870912",
            "memory.swap.max": "0",
            "pids.max": "64",
        }
    elif case == "pids":
        actual = json.loads(stdout)
        assert actual["limit_denied"] is True and 0 < actual["children"] < 64
    elif case == "oom":
        assert result["exit_code"] == 137 and result["oom_killed"] is True
        assert receipt["failure_code"] == "SANDBOX_OOM"
    elif case == "output":
        assert stdout == b"x" * 1048576 and receipt["failure_code"] == "SANDBOX_OUTPUT_LIMIT"
    elif case == "timeout":
        assert 30 <= receipt["wall_seconds"] < 60 and result["exit_code"] == 137
    elif case == "cancel":
        assert receipt["wall_seconds"] < 30 and receipt["failure_code"] == "SANDBOX_CANCELLED"
    else:
        assert json.loads(stdout)["spawned_child"] > 1 and result["exit_code"] == 0
