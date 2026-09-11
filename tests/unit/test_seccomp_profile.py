"""Offline security checks for the pinned, server-owned Linux seccomp asset."""

import hashlib
import json
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[2] / "infra" / "sandbox"
NETWORK = frozenset(
    {
        "accept",
        "accept4",
        "bind",
        "connect",
        "getpeername",
        "getsockname",
        "getsockopt",
        "listen",
        "recv",
        "recvfrom",
        "recvmmsg",
        "recvmmsg_time64",
        "recvmsg",
        "send",
        "sendmmsg",
        "sendmsg",
        "sendto",
        "setsockopt",
        "shutdown",
        "socket",
        "socketcall",
        "socketpair",
    }
)


def test_upstream_bytes_are_pinned_and_licensed() -> None:
    """Changing the baseline requires an explicit source and license review."""
    assert hashlib.sha256((ASSETS / "upstream/moby-default.json").read_bytes()).hexdigest() == (
        "536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74"
    )
    assert hashlib.sha256((ASSETS / "upstream/LICENSE.moby").read_bytes()).hexdigest() == (
        "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
    )


def test_derivative_only_removes_network_allowances() -> None:
    """Compare every argument, capability and architecture guard against upstream."""
    upstream = json.loads((ASSETS / "upstream/moby-default.json").read_bytes())
    expected_groups = []
    for group in upstream["syscalls"]:
        if group["action"] == "SCMP_ACT_ALLOW":
            group["names"] = [name for name in group["names"] if name not in NETWORK]
        if group["names"]:
            expected_groups.append(group)
    upstream["syscalls"] = expected_groups
    raw = (ASSETS / "python-no-network-v1.json").read_bytes()
    assert raw == (json.dumps(upstream, indent=2) + "\n").encode("utf-8")
    assert upstream["defaultAction"] == "SCMP_ACT_ERRNO"
    assert upstream["defaultErrnoRet"] == 1
    assert len(expected_groups) == 30


@pytest.mark.parametrize("syscall", sorted(NETWORK))
def test_network_denied_in_every_conditional_group(syscall: str) -> None:
    """No family, argument, capability, or architecture exception may reopen sockets."""
    profile = json.loads((ASSETS / "python-no-network-v1.json").read_bytes())
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
    for group in profile["syscalls"]:
        assert not (syscall in group["names"] and group["action"] == "SCMP_ACT_ALLOW")


@pytest.mark.parametrize("syscall", ["io_uring_setup", "io_uring_enter", "io_uring_register"])
def test_async_kernel_network_bypass_not_allowlisted(syscall: str) -> None:
    """io_uring must stay denied because its operations can create and use sockets."""
    profile = json.loads((ASSETS / "python-no-network-v1.json").read_bytes())
    assert all(syscall not in group["names"] for group in profile["syscalls"])


def test_basic_cpu_file_and_subprocess_calls_remain_available() -> None:
    """A static compatibility inventory does not substitute for container probes."""
    profile = json.loads((ASSETS / "python-no-network-v1.json").read_bytes())
    unconditional = {
        name
        for group in profile["syscalls"]
        if set(group) == {"names", "action"} and group["action"] == "SCMP_ACT_ALLOW"
        for name in group["names"]
    }
    assert {
        "read",
        "write",
        "openat",
        "close",
        "newfstatat",
        "lseek",
        "mmap",
        "mprotect",
        "munmap",
        "brk",
        "getrandom",
        "futex",
        "clock_gettime",
        "rt_sigaction",
        "rt_sigprocmask",
        "getpid",
        "getppid",
        "fork",
        "vfork",
        "execve",
        "pipe2",
        "dup2",
        "wait4",
        "kill",
        "exit_group",
    } <= unconditional
    clone = [group for group in profile["syscalls"] if group["names"] == ["clone"]]
    assert len(clone) == 2
    assert all(group["args"][0]["op"] == "SCMP_CMP_MASKED_EQ" for group in clone)
    assert all(group["args"][0]["value"] == 2114060288 for group in clone)
    assert any(
        group["names"] == ["clone3"]
        and group["action"] == "SCMP_ACT_ERRNO"
        and group["errnoRet"] == 38
        for group in profile["syscalls"]
    )


def test_supported_architecture_is_explicit() -> None:
    """The current executor targets Linux amd64; the upstream map is not admission."""
    profile = json.loads((ASSETS / "python-no-network-v1.json").read_bytes())
    assert profile["archMap"][0] == {
        "architecture": "SCMP_ARCH_X86_64",
        "subArchitectures": ["SCMP_ARCH_X86", "SCMP_ARCH_X32"],
    }
    readme = (ASSETS / "README.md").read_text(encoding="utf-8")
    assert "linux/amd64" in readme
    assert "no fallback" in readme
