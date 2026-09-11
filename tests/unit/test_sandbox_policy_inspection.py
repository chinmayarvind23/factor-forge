"""Independent synthetic mutations of create-time evidence; no Docker calls occur."""

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from factorforge.domain.errors import ResearchError
from factorforge.sandbox.docker import PYTHON_IMAGE, DockerRuntime
from factorforge.sandbox.image_binding import PYTHON_REFERENCE

PROFILE = Path(__file__).resolve().parents[2] / "infra/sandbox/python-no-network-v1.json"
NONCE = "a" * 32
IDENTITY = "b" * 64
LAUNCHER = "print('synthetic inspection fixture')"
IMAGE = {"Id": PYTHON_IMAGE, "Config": {"Env": ["PATH=/usr/local/bin:/usr/bin", "LANG=C"]}}


@pytest.fixture
def inspection_case(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[DockerRuntime, Path, dict[str, Any]]]:
    """Use a minimal authored daemon record, never captured developer paths or credentials."""
    with TemporaryDirectory(prefix="factorforge-inspection-test-") as directory:
        root = Path(directory)
        runtime = DockerRuntime(
            binary=Path(sys.executable), endpoint="unix:///var/run/docker.sock", config=root
        )
        mount = root / "input"
        mount.mkdir()
        value: dict[str, Any] = {
            "Id": IDENTITY,
            "Name": "/factorforge-" + NONCE,
            "Image": PYTHON_IMAGE,
            "State": {
                "Status": "created",
                "Running": False,
                "Paused": False,
                "Restarting": False,
                "Dead": False,
                "Pid": 0,
                "OOMKilled": False,
            },
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "Privileged": False,
                "NanoCpus": 1000000000,
                "Memory": 536870912,
                "MemorySwap": 536870912,
                "PidsLimit": 64,
                "IpcMode": "private",
                "CgroupnsMode": "private",
                "PidMode": "",
                "UTSMode": "",
                "UsernsMode": "",
                "ShmSize": 1048576,
                "Runtime": "runc",
                "AutoRemove": False,
                "PublishAllPorts": False,
                "OomKillDisable": False,
                "CapDrop": ["ALL"],
                "CapAdd": None,
                "Devices": [],
                "DeviceRequests": None,
                "DeviceCgroupRules": None,
                "Binds": None,
                "VolumesFrom": None,
                "PortBindings": {},
                "GroupAdd": None,
                "ExtraHosts": None,
                "LogConfig": {"Type": "none", "Config": {}},
                "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
                "Tmpfs": {"/tmp": "rw,nosuid,nodev,noexec,size=67108864,mode=1777"},
                "SecurityOpt": ["no-new-privileges=true", "seccomp=" + PROFILE.read_text()],
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": str(mount),
                        "Target": "/input",
                        "ReadOnly": True,
                        "BindOptions": {"NonRecursive": True},
                    }
                ],
                "Ulimits": [
                    {"Name": "core", "Hard": 0, "Soft": 0},
                    {"Name": "nofile", "Hard": 256, "Soft": 256},
                ],
                "MaskedPaths": [
                    "/proc/acpi",
                    "/proc/asound",
                    "/proc/interrupts",
                    "/proc/kcore",
                    "/proc/keys",
                    "/proc/latency_stats",
                    "/proc/sched_debug",
                    "/proc/scsi",
                    "/proc/timer_list",
                    "/proc/timer_stats",
                    "/sys/devices/virtual/powercap",
                    "/sys/firmware",
                ],
                "ReadonlyPaths": [
                    "/proc/bus",
                    "/proc/fs",
                    "/proc/irq",
                    "/proc/sys",
                    "/proc/sysrq-trigger",
                ],
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(mount),
                    "Destination": "/input",
                    "RW": False,
                    "Propagation": "rprivate",
                    "Mode": "",
                }
            ],
            "NetworkSettings": {"Networks": {"none": {}}, "Ports": {}},
            "Config": {
                "Env": [
                    "PATH=/usr/local/bin:/usr/bin",
                    "LANG=C",
                    "PYTHONHASHSEED=7",
                    "HOME=/tmp",
                    "PYTHONPATH=",
                    "PYTHONNOUSERSITE=1",
                    "PYTHONDONTWRITEBYTECODE=1",
                    "OMP_NUM_THREADS=1",
                ],
                "Entrypoint": ["/usr/local/bin/python"],
                "Cmd": ["-B", "-s", "-P", "-c", LAUNCHER],
                "User": "65532:65532",
                "WorkingDir": "/tmp",
                "Hostname": "factorforge",
                "OpenStdin": False,
                "Tty": False,
                "AttachStdin": False,
                "AttachStdout": True,
                "AttachStderr": True,
                "StdinOnce": False,
                "Healthcheck": {"Test": ["NONE"]},
                "Volumes": None,
                "Image": PYTHON_REFERENCE,
            },
        }

        def inspect(identity: str, nonce: str) -> dict[str, Any]:
            """Keep ownership arguments observable while replacing only the daemon transport."""
            assert (identity, nonce) == (IDENTITY, NONCE)
            return value

        monkeypatch.setattr(runtime, "inspect_owned", inspect)
        yield runtime, mount, value


def verify(case: tuple[DockerRuntime, Path, dict[str, Any]]) -> dict[str, Any]:
    """Supply fixed trusted controller expectations to the verifier under review."""
    runtime, mount, _ = case
    return runtime.verify_created(
        IDENTITY,
        nonce=NONCE,
        mount=mount,
        seccomp=PROFILE,
        image=IMAGE,
        seed=7,
        launcher=LAUNCHER,
    )


def test_authored_valid_policy_is_accepted(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
) -> None:
    """The negative matrix needs a positive control independent of the actual daemon."""
    assert verify(inspection_case) is inspection_case[2]


@pytest.mark.parametrize("image", [PYTHON_IMAGE, "python:latest", None])
def test_created_request_image_retains_fixed_repository_reference(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
    image: str | None,
) -> None:
    """Matching effective filesystem identity does not permit a different create reference."""
    inspection_case[2]["Config"]["Image"] = image
    with pytest.raises(ResearchError) as error:
        verify(inspection_case)
    assert error.value.code == "SANDBOX_POLICY_MISMATCH"


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    [
        ("HostConfig", "NetworkMode", "host"),
        ("HostConfig", "ReadonlyRootfs", False),
        ("HostConfig", "ReadonlyRootfs", 1),
        ("HostConfig", "Privileged", True),
        ("HostConfig", "NanoCpus", 0),
        ("HostConfig", "Memory", 0),
        ("HostConfig", "MemorySwap", -1),
        ("HostConfig", "PidsLimit", -1),
        ("HostConfig", "PidsLimit", 64.0),
        ("HostConfig", "IpcMode", "host"),
        ("HostConfig", "CgroupnsMode", "host"),
        ("HostConfig", "PidMode", "host"),
        ("HostConfig", "UTSMode", "host"),
        ("HostConfig", "ShmSize", 67108864),
        ("HostConfig", "Runtime", "nvidia"),
        ("HostConfig", "AutoRemove", True),
        ("HostConfig", "PublishAllPorts", True),
        ("HostConfig", "CapDrop", []),
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("HostConfig", "Devices", [{"PathOnHost": "/dev/example"}]),
        ("HostConfig", "DeviceRequests", [{"Count": -1}]),
        ("HostConfig", "DeviceCgroupRules", ["a *:* rwm"]),
        ("HostConfig", "Binds", ["/synthetic-host:/extra"]),
        ("HostConfig", "VolumesFrom", ["other"]),
        ("HostConfig", "PortBindings", {"80/tcp": [{"HostPort": "80"}]}),
        ("HostConfig", "GroupAdd", ["0"]),
        ("HostConfig", "ExtraHosts", ["host:host-gateway"]),
        ("HostConfig", "LogConfig", {"Type": "json-file", "Config": {}}),
        ("HostConfig", "RestartPolicy", {"Name": "always", "MaximumRetryCount": 0}),
        ("HostConfig", "Tmpfs", {"/tmp": "rw,size=67108864"}),
        ("Config", "Entrypoint", ["/bin/sh"]),
        ("Config", "Cmd", ["-c", "print('changed')"]),
        ("Config", "User", "0:0"),
        ("Config", "WorkingDir", "/input"),
        ("Config", "Hostname", "other"),
        ("Config", "OpenStdin", True),
        ("Config", "Tty", True),
        ("Config", "Healthcheck", {"Test": ["CMD", "python"]}),
        ("Config", "Volumes", {"/extra": {}}),
        ("State", "Status", "running"),
    ],
)
def test_declared_controls_reject_mutation(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
    section: str,
    field: str,
    replacement: Any,
) -> None:
    """Mutate one policy dimension so a rejection cannot hide behind another mismatch."""
    inspection_case[2][section][field] = replacement
    with pytest.raises(ResearchError) as error:
        verify(inspection_case)
    assert error.value.code == "SANDBOX_POLICY_MISMATCH"


@pytest.mark.parametrize("field", ["HostConfig", "Config", "State"])
@pytest.mark.parametrize("replacement", [None, [], "invalid", 1])
def test_malformed_sections_fail_with_typed_error(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
    field: str,
    replacement: Any,
) -> None:
    """Malformed daemon shapes must not escape as incidental Python exceptions."""
    inspection_case[2][field] = replacement
    with pytest.raises(ResearchError) as error:
        verify(inspection_case)
    assert error.value.code == "SANDBOX_POLICY_MISMATCH"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "added", "changed", "malformed"])
def test_environment_is_exact(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
    mutation: str,
) -> None:
    """Image-declared values plus the fixed controller overrides form the full environment."""
    env = inspection_case[2]["Config"]["Env"]
    if mutation == "missing":
        env.pop()
    elif mutation == "duplicate":
        env.append(env[0])
    elif mutation == "added":
        env.append("UNEXPECTED=synthetic")
    elif mutation == "changed":
        env[2] = "PYTHONHASHSEED=8"
    else:
        env[0] = "NO_EQUALS"
    with pytest.raises(ResearchError):
        verify(inspection_case)


@pytest.mark.parametrize(
    "mutation",
    [
        "default",
        "socket",
        "socketpair",
        "socketcall",
        "conditional",
        "unconfined",
        "missing_nnp",
        "extra",
        "malformed",
    ],
)
def test_seccomp_cannot_be_weakened(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
    mutation: str,
) -> None:
    """The whole decoded pinned profile must match, including conditional syscall groups."""
    profile = json.loads(PROFILE.read_bytes())
    security = ["no-new-privileges=true"]
    if mutation == "default":
        profile["defaultAction"] = "SCMP_ACT_ALLOW"
    elif mutation in {"socket", "socketpair", "socketcall"}:
        profile["syscalls"][0]["names"].append(mutation)
    elif mutation == "conditional":
        profile["syscalls"].append(
            {
                "names": ["socket"],
                "action": "SCMP_ACT_ALLOW",
                "args": [{"index": 0, "value": 1, "op": "SCMP_CMP_EQ"}],
            }
        )
    security.append("seccomp=" + json.dumps(profile))
    if mutation == "unconfined":
        security[1] = "seccomp=unconfined"
    elif mutation == "missing_nnp":
        security.pop(0)
    elif mutation == "extra":
        security.append("apparmor=unconfined")
    elif mutation == "malformed":
        security[1] = "seccomp={"
    inspection_case[2]["HostConfig"]["SecurityOpt"] = security
    with pytest.raises(ResearchError):
        verify(inspection_case)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("Type", "volume"),
        ("Source", "/different-synthetic-source"),
        ("Target", "/other"),
        ("ReadOnly", False),
        ("ReadOnly", 1),
        ("BindOptions", {"NonRecursive": False}),
    ],
)
def test_mount_request_cannot_change(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
    field: str,
    replacement: Any,
) -> None:
    """A readonly nonrecursive bind must point at the exact controller staging directory."""
    inspection_case[2]["HostConfig"]["Mounts"][0][field] = replacement
    with pytest.raises(ResearchError):
        verify(inspection_case)


def test_resolved_image_must_match(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
) -> None:
    """The actual resolved image identity matters even when its displayed command matches."""
    inspection_case[2]["Image"] = "sha256:" + "c" * 64
    with pytest.raises(ResearchError):
        verify(inspection_case)


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    [
        ("HostConfig", "OomKillDisable", True),
        ("HostConfig", "Ulimits", []),
        ("HostConfig", "MaskedPaths", []),
        ("HostConfig", "ReadonlyPaths", []),
        ("HostConfig", "UsernsMode", "host"),
        ("Config", "AttachStdin", True),
        ("Config", "AttachStdout", False),
        ("Config", "AttachStderr", False),
        ("State", "Running", True),
        ("State", "Pid", 123),
        ("NetworkSettings", "Networks", {"bridge": {}}),
    ],
)
def test_effective_safety_controls_must_match(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
    section: str,
    field: str,
    replacement: Any,
) -> None:
    """Detect omitted checks whose mismatch contradicts the fixed safe create policy."""
    inspection_case[2][section][field] = replacement
    with pytest.raises(ResearchError):
        verify(inspection_case)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("RW", True),
        ("Source", "/different-synthetic-source"),
        ("Destination", "/other"),
        ("Propagation", "shared"),
        ("Type", "volume"),
    ],
)
def test_effective_mounts_cannot_contradict_requested_mounts(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
    field: str,
    replacement: Any,
) -> None:
    """Daemon-effective mounts must agree with the requested readonly isolated bind."""
    inspection_case[2]["Mounts"][0][field] = replacement
    with pytest.raises(ResearchError):
        verify(inspection_case)


@pytest.mark.parametrize("count", [0, 2])
@pytest.mark.parametrize("effective", [False, True])
def test_exactly_one_mount_is_required(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
    count: int,
    effective: bool,
) -> None:
    """Extra or missing mounts must fail in requested and daemon-effective inventories."""
    container = inspection_case[2]
    target = container if effective else container["HostConfig"]
    target["Mounts"] = target["Mounts"] * count
    with pytest.raises(ResearchError):
        verify(inspection_case)


@pytest.mark.parametrize("field", ["Mounts", "SecurityOpt", "RestartPolicy"])
@pytest.mark.parametrize("replacement", [None, [None], "invalid", 1])
def test_malformed_nested_controls_fail_with_typed_error(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
    field: str,
    replacement: Any,
) -> None:
    """Ill-shaped nested records must not produce incidental indexing or attribute errors."""
    inspection_case[2]["HostConfig"][field] = replacement
    with pytest.raises(ResearchError) as error:
        verify(inspection_case)
    assert error.value.code == "SANDBOX_POLICY_MISMATCH"


def test_equivalent_json_formatting_and_environment_order_are_accepted(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
) -> None:
    """Daemon JSON whitespace and unordered environment lists do not weaken the policy."""
    profile = json.loads(PROFILE.read_bytes())
    inspection_case[2]["HostConfig"]["SecurityOpt"] = [
        "seccomp=" + json.dumps(profile, sort_keys=True, separators=(",", ":")),
        "no-new-privileges=true",
    ]
    inspection_case[2]["Config"]["Env"].reverse()
    assert verify(inspection_case) is inspection_case[2]


def test_seccomp_boolean_cannot_impersonate_integer(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
) -> None:
    """Python dict equality conflates True and 1; a policy record must preserve JSON types."""
    profile = json.loads(PROFILE.read_bytes())
    profile["defaultErrnoRet"] = True
    inspection_case[2]["HostConfig"]["SecurityOpt"][1] = "seccomp=" + json.dumps(profile)
    with pytest.raises(ResearchError):
        verify(inspection_case)


def test_nonrecursive_boolean_cannot_be_numeric(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
) -> None:
    """A malformed bind boolean must not gain approval through Python numeric equality."""
    inspection_case[2]["HostConfig"]["Mounts"][0]["BindOptions"]["NonRecursive"] = 1
    with pytest.raises(ResearchError):
        verify(inspection_case)


def test_ulimit_integer_cannot_be_boolean(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
) -> None:
    """Resource-limit types remain significant even when False compares equal to zero."""
    inspection_case[2]["HostConfig"]["Ulimits"][0]["Hard"] = False
    with pytest.raises(ResearchError):
        verify(inspection_case)


def test_network_inventory_cannot_be_list_of_names(
    inspection_case: tuple[DockerRuntime, Path, dict[str, Any]],
) -> None:
    """A set conversion must not approve a malformed list in place of network objects."""
    inspection_case[2]["NetworkSettings"]["Networks"] = ["none"]
    with pytest.raises(ResearchError):
        verify(inspection_case)
