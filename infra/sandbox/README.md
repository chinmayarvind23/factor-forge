# Python sandbox seccomp policy

`python-no-network-v1.json` is a modified Moby default seccomp allowlist. It uses
`SCMP_ACT_ERRNO` (EPERM) for unlisted system calls. FactorForge removed all 22
socket/network syscall names listed below from every allow group, including
conditional groups. This denies socket creation for every address family,
including AF_UNIX, AF_INET, AF_INET6, AF_NETLINK, AF_ALG and AF_VSOCK, and denies
the legacy `socketcall` multiplexor. This profile does not add any permissions.

The executor must explicitly supply this reviewed asset through Docker's
`--security-opt seccomp=<server-owned-path>` option. An absent, changed, or
unloadable profile must stop admission; there is no fallback to `unconfined` or
the daemon's built-in profile. The initial executor target is **linux/amd64**.
The retained upstream architecture map includes compatibility architectures;
it does not authorize other host/image platforms. Reject unsupported platforms
before execution. A runtime must reject unknown architectures rather than
silently running without seccomp.

## Upstream attribution and identities

Moby Authors provide the source profile under Apache License 2.0. The original
license is preserved at [upstream/LICENSE.moby](upstream/LICENSE.moby). The
unmodified source bytes are at [upstream/moby-default.json](upstream/moby-default.json).
FactorForge's modification is the removal described here; the derived JSON is
also distributed under Apache License 2.0. This attribution does not change the
license of unrelated repository files.

Pinned upstream commit: `61eaf32614c7c71b60bd8927d3e6a4ffc8ff1f31`.

- [Original seccomp profile](https://github.com/moby/profiles/blob/61eaf32614c7c71b60bd8927d3e6a4ffc8ff1f31/seccomp/default.json)
- [Original license](https://github.com/moby/profiles/blob/61eaf32614c7c71b60bd8927d3e6a4ffc8ff1f31/LICENSE)
- [Docker seccomp documentation](https://docs.docker.com/engine/security/seccomp/)

| File | Bytes | SHA-256 of raw bytes |
| --- | ---: | --- |
| `upstream/moby-default.json` | 13470 | `536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74` |
| `upstream/LICENSE.moby` | 11358 | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| `python-no-network-v1.json` | 15597 | `9033f43b539af2002ca705475be2b8b6633a9fd1fae924c9f58adb8aebd8a334` |

The directory's `.gitattributes` preserves those bytes across checkouts.

## Exact derivation and static verification

Parse the pinned upstream JSON. In each `SCMP_ACT_ALLOW` rule, filter these names
from its `names` array, preserving order. Remove a rule only if its resulting
array is empty. Preserve every other field, rule and ordering. Serialize with
Python `json.dumps(profile, indent=2)` followed by one LF, encoded as UTF-8.

```text
accept accept4 bind connect getpeername getsockname getsockopt listen
recv recvfrom recvmmsg recvmmsg_time64 recvmsg send sendmmsg sendmsg sendto
setsockopt shutdown socket socketcall socketpair
```

This removes 24 occurrences of 22 names and three empty conditional socket
rules, leaving 30 syscall groups. All capability, kernel-version, architecture,
argument-mask, and explicit errno restrictions remain unchanged. The upstream
profile already excludes `io_uring_setup`, `io_uring_enter`, and
`io_uring_register`; static tests ensure these network-capable interfaces stay
excluded. Any upstream update requires a new review and explicit hash changes.

From the repository root, run:

```text
uv run pytest tests/unit/test_seccomp_profile.py -q
```

These checks pin the upstream source/license, compare the complete derivative,
check every conditional allow group for networking, and inventory basic Python
calls. They do not execute Docker or demonstrate kernel enforcement.

## Compatibility and boundary

The retained calls cover ordinary CPU arithmetic, interpreter memory allocation,
signals, clocks, regular-file access, pipes, process creation and process waits.
The upstream argument-limited `clone` rules remain; the no-CAP_SYS_ADMIN
`clone3` rule returns ENOSYS to support libc fallback. This is a static assessment.
Actual Python startup, file I/O, bounded subprocess and PID-limit probes still
need to pass on the pinned image and the target Docker/libseccomp runtime.
Unknown syscall names on older runtimes may make profile loading fail; that
failure must remain visible. No compatibility fallback is permitted.

Python features that create sockets, including socket-based IPC and the usual
asyncio event-loop wakeup socket, are deliberately outside this first profile.
Generic FD operations such as `read`, `write`, `sendfile`, `splice`, and `ioctl`
remain available because they also serve regular files and pipes. Seccomp does
not inspect pathname strings or guarantee that an inherited descriptor is safe.
The controller must expose only pipe/file descriptors, never pass connected
sockets or host device/daemon mounts, and keep capability-drop, private PID/IPC
namespaces, nonroot UID, no-new-privileges, read-only mounts, and resource limits.
Docker `--network none` remains required in addition to this syscall policy.

This is a defense layer within a shared-kernel container. The profile alone does
not establish isolation from kernel vulnerabilities, correct mount ownership,
bounded resource use, or successful cleanup.
