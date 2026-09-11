"""Independent Docker boundary tests use controlled CLI replies and never mutate a daemon."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from factorforge.domain.errors import ResearchError
from factorforge.sandbox.docker import OWNERSHIP_LABEL, PYTHON_IMAGE, DockerRuntime
from factorforge.sandbox.process import CommandResult

NONCE = "1" * 32
IDENTITY = "2" * 64
OTHER = "3" * 64


@pytest.fixture
def runtime() -> Iterator[DockerRuntime]:
    """Owned plain directories avoid pytest's untrusted Windows current symlinks."""
    with TemporaryDirectory(prefix="factorforge-docker-review-") as temporary:
        yield DockerRuntime(
            binary=Path(sys.executable),
            endpoint="unix:///var/run/docker.sock",
            config=Path(temporary),
        )


def daemon_info() -> dict[str, Any]:
    """Use the actual local daemon's readiness key spelling without copying private diagnostics."""
    return {
        "OSType": "linux",
        "Architecture": "x86_64",
        "CgroupVersion": "2",
        "MemoryLimit": True,
        "SwapLimit": True,
        "PidsLimit": True,
        "CpuCfsPeriod": True,
        "CpuCfsQuota": True,
        "SecurityOptions": ["name=seccomp,profile=builtin"],
    }


def image_info() -> dict[str, Any]:
    """Provide the expected immutable image identity and absence of inherited volumes."""
    return {
        "Id": PYTHON_IMAGE,
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {"Volumes": None},
        "RepoDigests": ["python@" + PYTHON_IMAGE],
    }


def owned_info() -> dict[str, Any]:
    """A concrete full ID, exact nonce name and ownership label must agree."""
    return {
        "Id": IDENTITY,
        "Name": "/factorforge-" + NONCE,
        "Config": {"Labels": {OWNERSHIP_LABEL: NONCE}},
    }


def replies(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, values: list[object]
) -> list[tuple[str, ...]]:
    """Replace transport with ordered bounded replies while recording every intended operation."""
    calls: list[tuple[str, ...]] = []

    def command(args: tuple[str, ...], **kwargs: Any) -> CommandResult:
        """Only controlled data reaches Docker JSON and ownership logic in these tests."""
        calls.append(args)
        assert values, "Unexpected controller call"
        value = values.pop(0)
        if isinstance(value, CommandResult):
            return value
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        return CommandResult(raw, b"", 0, "exited")

    monkeypatch.setattr(runtime, "command", command)
    return calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("SecurityOptions", None),
        ("SecurityOptions", 3),
        ("SecurityOptions", {"name=seccomp": True}),
        ("SecurityOptions", ["not-name=seccomp"]),
        ("CpuCfsPeriod", False),
        ("CpuCfsQuota", False),
        ("CpuCfsQuota", None),
        ("MemoryLimit", 1),
    ],
)
def test_preflight_rejects_malformed_or_missing_security_controls(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    """A readiness claim needs correctly shaped seccomp and available CPU quota controls."""
    info = daemon_info()
    info[field] = value
    calls = replies(runtime, monkeypatch, [info, [image_info()]])
    with pytest.raises(ResearchError):
        runtime.preflight(PYTHON_IMAGE)
    assert len(calls) == 1


@pytest.mark.parametrize("config", [None, [], "unstructured"])
def test_bad_image_config_is_typed_invalid(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, config: object
) -> None:
    """Malformed nested image metadata cannot escape as an AttributeError."""
    image = image_info()
    image["Config"] = config
    replies(runtime, monkeypatch, [daemon_info(), [image]])
    with pytest.raises(ResearchError):
        runtime.preflight(PYTHON_IMAGE)


def test_valid_preflight_returns_verified_metadata(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An accepted profile requires two complete successful control-plane replies."""
    calls = replies(runtime, monkeypatch, [daemon_info(), [image_info()]])
    result = runtime.preflight(PYTHON_IMAGE)
    assert result == {"daemon": daemon_info(), "image": image_info()}
    assert calls == [
        ("info", "--format", "{{json .}}"),
        ("image", "inspect", "python@" + PYTHON_IMAGE),
    ]


@pytest.mark.parametrize(
    "raw,array",
    [
        (b"{", False),
        (b"[]", False),
        (b"null", False),
        (b"[]", True),
        (b"[{},{}]", True),
        (b"[null]", True),
        (b"\xff", False),
    ],
)
def test_malformed_daemon_json_is_typed(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, raw: bytes, array: bool
) -> None:
    """Invalid syntax, encoding and top-level shapes cannot become control evidence."""
    replies(runtime, monkeypatch, [raw])
    with pytest.raises(ResearchError):
        runtime.object(("info",), array=array)


@pytest.mark.parametrize("config", [None, {"Labels": None}, {"Labels": []}])
def test_cleanup_malformed_ownership_is_unconfirmed(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, config: object
) -> None:
    """Cleanup fails closed without raw nested-shape exceptions or a removal attempt."""
    info = owned_info()
    info["Config"] = config
    calls = replies(runtime, monkeypatch, [(IDENTITY + "\n").encode(), [info]])
    assert runtime.remove_owned(NONCE) is False
    assert not any("rm" in call for call in calls)


@pytest.mark.parametrize(
    "field,value",
    [("Id", OTHER), ("Name", "/unrelated"), ("Config", {"Labels": {OWNERSHIP_LABEL: "0" * 32}})],
)
def test_wrong_ownership_never_removes(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    """Even a matching name listing does not authorize removing another container."""
    info = owned_info()
    info[field] = value
    calls = replies(runtime, monkeypatch, [(IDENTITY + "\n").encode(), [info]])
    assert runtime.remove_owned(NONCE) is False
    assert not any("rm" in call for call in calls)


def test_removal_requires_successful_post_remove_absence(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One successful rm reply alone does not prove the container is gone."""
    calls = replies(runtime, monkeypatch, [(IDENTITY + "\n").encode(), [owned_info()], b"ok", b""])
    assert runtime.remove_owned(NONCE) is True
    assert ("container", "rm", "--force", IDENTITY) in calls
    assert calls[-1][0:2] == ("container", "ls")


@pytest.mark.parametrize(
    "last",
    [
        CommandResult(b"", b"private daemon error", 1, "exited"),
        CommandResult(b"", b"", -1, "timed_out"),
        (IDENTITY + "\n").encode(),
    ],
)
def test_failed_or_nonempty_cleanup_confirmation_stays_unconfirmed(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, last: CommandResult | bytes
) -> None:
    """Transport errors and a still-present owned ID cannot claim successful cleanup."""
    responses: list[object] = [(IDENTITY + "\n").encode(), [owned_info()], b"ok", last]
    if isinstance(last, bytes):
        responses.append([owned_info()])
    replies(runtime, monkeypatch, responses)
    assert runtime.remove_owned(NONCE) is False


def test_replacement_name_race_never_removes_the_replacement(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After deleting the owned ID, a different container at that name remains untouched."""
    replacement = owned_info()
    replacement["Id"] = OTHER
    replacement["Config"] = {"Labels": {OWNERSHIP_LABEL: "0" * 32}}
    calls = replies(
        runtime,
        monkeypatch,
        [(IDENTITY + "\n").encode(), [owned_info()], b"ok", (OTHER + "\n").encode(), [replacement]],
    )
    assert runtime.remove_owned(NONCE) is False
    assert [call for call in calls if "rm" in call] == [("container", "rm", "--force", IDENTITY)]


def test_absence_can_be_confirmed_without_removal(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A never-created name needs healthy empty listings, not a fabricated container ID."""
    calls = replies(runtime, monkeypatch, [b"", b""])
    assert runtime.remove_owned(NONCE) is True
    assert len(calls) == 2 and not any("rm" in call for call in calls)


def test_create_arguments_are_fixed_and_generated_code_is_not_a_host_command(
    runtime: DockerRuntime,
) -> None:
    """The server pins image, nonroot identity, isolated mounts and resource flags before launch."""
    seccomp = Path("infra/sandbox/python-no-network-v1.json").resolve()
    with TemporaryDirectory(prefix="factorforge-input-review-") as temporary:
        args = runtime.create_args(
            nonce=NONCE,
            mount=Path(temporary),
            seccomp=seccomp,
            image=PYTHON_IMAGE,
            seed=7,
            launcher="trusted_launcher()",
        )
    assert args[0] == "create" and args[-2:] == ("-c", "trusted_launcher()")
    assert args[args.index("--entrypoint") + 2] == "python@" + PYTHON_IMAGE
    for flag, value in [
        ("--network", "none"),
        ("--user", "65532:65532"),
        ("--cap-drop", "ALL"),
        ("--cpus", "1"),
        ("--memory", "536870912"),
        ("--pids-limit", "64"),
        ("--pull", "never"),
    ]:
        assert args[args.index(flag) + 1] == value
    assert "--read-only" in args and "--privileged" not in args
    assert (
        "no-new-privileges=true" in args
        and args[args.index("--entrypoint") + 1] == "/usr/local/bin/python"
    )


@pytest.mark.parametrize("nonce", ["--help", "", "f" * 31, "F" * 32])
def test_invalid_nonce_never_reaches_docker(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, nonce: str
) -> None:
    """Names cannot turn into caller-selected flags or ambiguous ownership identities."""
    calls = replies(runtime, monkeypatch, [])
    with pytest.raises(ResearchError):
        runtime.find_owned(nonce)
    assert not calls


def test_transport_prefix_and_environment_ignore_caller_docker_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The trusted local endpoint and empty configuration take precedence over host Docker state."""
    monkeypatch.setenv("DOCKER_HOST", "tcp://not-allowed:2375")
    monkeypatch.setenv("DOCKER_CONTEXT", "untrusted-context")
    monkeypatch.setenv("DOCKER_CONFIG", "untrusted-config")
    monkeypatch.setenv("HTTP_PROXY", "http://untrusted-proxy")
    monkeypatch.setenv("FACTORFORGE_FAKE_SECRET", "should-not-pass")
    import factorforge.sandbox.docker as module

    calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    def fake_run(args: tuple[str, ...], **kwargs: Any) -> CommandResult:
        """Observe the controller request without invoking any daemon or process."""
        calls.append((args, kwargs))
        return CommandResult(b"ok", b"", 0, "exited")

    monkeypatch.setattr(module, "run_command", fake_run)
    with TemporaryDirectory(prefix="factorforge-config-review-") as temporary:
        config = Path(temporary)
        value = DockerRuntime(
            binary=Path(sys.executable), endpoint="unix:///var/run/docker.sock", config=config
        )
        value.command(("version",), timeout=3, output_limit=128)
        assert calls[0][0] == (
            str(Path(sys.executable)),
            "--host",
            "unix:///var/run/docker.sock",
            "--config",
            str(config),
            "version",
        )
    env = calls[0][1]["environment"]
    assert not any(
        key in env
        for key in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_CONFIG",
            "HTTP_PROXY",
            "FACTORFORGE_FAKE_SECRET",
        )
    )
    assert env["DOCKER_CLI_HINTS"] == "false"
    assert calls[0][1]["timeout_seconds"] == 3 and calls[0][1]["output_limit"] == 128


def test_nonempty_config_and_relative_server_paths_are_rejected() -> None:
    """A developer's config cannot inject proxy defaults or credential helpers into the worker."""
    with TemporaryDirectory(prefix="factorforge-config-review-") as temporary:
        config = Path(temporary)
        with pytest.raises(ValueError):
            DockerRuntime(
                binary=Path("docker"), endpoint="unix:///var/run/docker.sock", config=config
            )
        (config / "config.json").write_text("{}")
        with pytest.raises(ValueError):
            DockerRuntime(
                binary=Path(sys.executable), endpoint="unix:///var/run/docker.sock", config=config
            )


@pytest.mark.parametrize("seed", [-1, 2**32, True])
def test_create_seed_bounds_reject_before_policy_read(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, seed: int
) -> None:
    """Seed validation cannot become a flag or an out-of-range interpreter environment value."""

    def forbidden(path: Path) -> None:
        """The changed seed must fail before reading any policy bytes."""
        raise AssertionError("Unexpected policy read")

    monkeypatch.setattr(runtime, "verify_seccomp", forbidden)
    with pytest.raises(ResearchError):
        runtime.create_args(
            nonce=NONCE,
            mount=Path.cwd(),
            seccomp=Path.cwd() / "missing",
            image=PYTHON_IMAGE,
            seed=seed,
            launcher="fixed",
        )


@pytest.mark.parametrize("part", ["bad,path", "bad\npath", 'bad"path'])
def test_mount_option_delimiters_are_rejected(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, part: str
) -> None:
    """A mount path cannot inject additional Docker mount CSV options."""

    def forbidden(path: Path) -> None:
        """Path syntax is rejected before policy access or any controller call."""
        raise AssertionError("Unexpected policy read")

    monkeypatch.setattr(runtime, "verify_seccomp", forbidden)
    with pytest.raises(ResearchError) as caught:
        runtime.create_args(
            nonce=NONCE,
            mount=Path.cwd() / part,
            seccomp=Path.cwd() / "missing",
            image=PYTHON_IMAGE,
            seed=1,
            launcher="fixed",
        )
    assert caught.value.code == "SANDBOX_PATH_INVALID"


@pytest.mark.parametrize(
    "response",
    [
        CommandResult(b"{}", b"", 0, "output_limit"),
        CommandResult(b"{}", b"", 0, "cancelled"),
        CommandResult(b"{}", b"", 1, "exited"),
    ],
)
def test_control_evidence_requires_complete_capture_and_success(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, response: CommandResult
) -> None:
    """Valid-looking stdout cannot override a resource, cancellation or process failure."""
    replies(runtime, monkeypatch, [response])
    with pytest.raises(ResearchError):
        runtime.object(("info",))


def test_cleanup_capture_retains_healthy_absence_and_stops_after_removal(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup evidence retains exact bounded replies and excludes unrelated later commands."""
    import factorforge.sandbox.docker as module

    responses = [
        (IDENTITY + "\n").encode(),
        json.dumps([owned_info()]).encode(),
        b"removed\n",
        b"",
        b"later",
    ]

    def fake_run(args: tuple[str, ...], **kwargs: Any) -> CommandResult:
        """Keep the real command recording path while replacing process execution only."""
        return CommandResult(responses.pop(0), b"", 0, "exited")

    monkeypatch.setattr(module, "run_command", fake_run)
    assert runtime.remove_owned(NONCE) is True
    saved = list(runtime.cleanup_evidence)
    assert len(saved) == 4
    assert saved[-1]["argv"][:2] == ("container", "ls")
    assert saved[-1]["stdout"] == "" and saved[-1]["exit"] == 0 and saved[-1]["reason"] == "exited"
    assert saved[1]["stdout"] == json.dumps([owned_info()])
    runtime.command(("version",))
    assert runtime.cleanup_evidence == saved


def test_failed_cleanup_transport_reply_remains_in_evidence(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unconfirmed cleanup keeps its failed control reply instead of implying empty success."""
    import factorforge.sandbox.docker as module

    def fake_run(args: tuple[str, ...], **kwargs: Any) -> CommandResult:
        """Supply one bounded timeout record with a retained diagnostic fragment."""
        return CommandResult(b"partial", b"controller timeout", None, "timed_out")

    monkeypatch.setattr(module, "run_command", fake_run)
    assert runtime.remove_owned(NONCE) is False
    assert len(runtime.cleanup_evidence) == 1
    assert runtime.cleanup_evidence[0]["reason"] == "timed_out"
    assert runtime.cleanup_evidence[0]["stdout"] == "partial"
    assert runtime.cleanup_evidence[0]["stderr"] == "controller timeout"


@pytest.mark.parametrize(
    "field,value",
    [
        ("RepoDigests", None),
        ("RepoDigests", []),
        ("RepoDigests", "python@" + PYTHON_IMAGE),
        ("RepoDigests", {"python@" + PYTHON_IMAGE: True}),
        ("RepoDigests", ["python@" + PYTHON_IMAGE, None]),
        ("RepoDigests", ["untrusted@" + PYTHON_IMAGE]),
        ("RepoDigests", ["python@sha256:" + "0" * 64]),
        ("Id", None),
        ("Id", []),
        ("Id", "sha256:" + "0" * 64),
        ("Id", "python@" + PYTHON_IMAGE),
    ],
)
def test_image_requires_exact_repository_digest_and_pinned_object_identity(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    """Neither a matching repository string nor a matching ID alone establishes image identity."""
    actual = image_info()
    actual[field] = value
    calls = replies(runtime, monkeypatch, [daemon_info(), [actual]])
    with pytest.raises(ResearchError) as error:
        runtime.preflight(PYTHON_IMAGE)
    assert error.value.code == "SANDBOX_IMAGE_INVALID"
    assert calls[-1] == ("image", "inspect", "python@" + PYTHON_IMAGE)


@pytest.mark.parametrize("field", ["RepoDigests", "Id"])
def test_missing_image_identity_is_typed_invalid(
    runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """Absent required metadata cannot silently substitute the requested digest."""
    actual = image_info()
    del actual[field]
    replies(runtime, monkeypatch, [daemon_info(), [actual]])
    with pytest.raises(ResearchError) as error:
        runtime.preflight(PYTHON_IMAGE)
    assert error.value.code == "SANDBOX_IMAGE_INVALID"
