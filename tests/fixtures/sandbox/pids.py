"""Bounded process-limit probe creates at most eighty children inside a 64-PID cgroup."""

import errno
import json
import os
import signal
import sys
from pathlib import Path

if sys.platform != "linux":
    raise RuntimeError("This diagnostic requires the reviewed Linux container")
if os.getuid() != 65532 or Path("/sys/fs/cgroup/pids.max").read_text().strip() != "64":
    raise RuntimeError("The bounded nonroot container profile is required")


def main() -> None:
    """Children do no work and are reaped even if the expected cgroup denial is absent."""
    children = []
    limited = False
    try:
        for _ in range(80):
            try:
                child = os.fork()
            except OSError as error:
                limited = error.errno == errno.EAGAIN
                break
            if child == 0:
                signal.pause()
                os._exit(0)
            children.append(child)
    finally:
        for child in children:
            os.kill(child, signal.SIGKILL)
        for child in children:
            os.waitpid(child, 0)
    print(json.dumps({"children": len(children), "limit_denied": limited}))


if __name__ == "__main__":
    main()
