"""Original bounded denial probes run only inside the reviewed Python container profile."""

import errno
import importlib.util
import json
import os
import socket
import sys
from pathlib import Path

if sys.platform != "linux":
    raise RuntimeError("This diagnostic requires the reviewed Linux container")


def denied_write(path: str) -> bool:
    """Attempt one tiny write and require a filesystem or permission denial."""
    try:
        with open(path, "wb") as stream:
            stream.write(b"probe")
    except OSError as error:
        return error.errno in {errno.EROFS, errno.EACCES, errno.EPERM}
    return False


def main() -> None:
    """Inspect identity/cgroups and deny sockets without sending traffic to any destination."""
    sockets = {}
    for family in (socket.AF_INET, socket.AF_INET6, socket.AF_UNIX, socket.AF_NETLINK, 40):
        try:
            connection = socket.socket(family, socket.SOCK_STREAM)
        except OSError as error:
            sockets[str(family)] = error.errno == errno.EPERM
        else:
            connection.close()
            sockets[str(family)] = False
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    observations = {
        "uid": os.getuid(),
        "gid": os.getgid(),
        "capabilities": status["CapEff"].strip(),
        "seccomp": status["Seccomp"].strip(),
        "no_new_privileges": status["NoNewPrivs"].strip(),
        "root_write_denied": denied_write("/forbidden-probe"),
        "input_write_denied": denied_write("/input/code.py"),
        "canary_not_mounted": not Path("/input/../host-canary.txt").exists(),
        "host_env_absent": "FACTORFORGE_HOST_ONLY" not in os.environ,
        "pip_absent": importlib.util.find_spec("pip") is None,
        "ensurepip_absent": importlib.util.find_spec("ensurepip") is None,
        "socket_denials": sockets,
        "cgroups": {
            name: (Path("/sys/fs/cgroup") / name).read_text().strip()
            for name in ("cpu.max", "memory.max", "memory.swap.max", "pids.max")
        },
    }
    print(json.dumps(observations, sort_keys=True))


if __name__ == "__main__":
    main()
