"""One bounded allocation intentionally exceeds this container's 512-MiB memory limit."""

import os
import sys
from pathlib import Path

if sys.platform != "linux":
    raise RuntimeError("This diagnostic requires the reviewed Linux container")
if os.getuid() != 65532 or Path("/sys/fs/cgroup/memory.max").read_text().strip() != "536870912":
    raise RuntimeError("The bounded nonroot container profile is required")

buffer = bytearray(600 * 1024 * 1024)
print(len(buffer))
