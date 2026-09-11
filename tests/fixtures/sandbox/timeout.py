"""A single CPU loop exercises the fixed 30-second controller deadline and one-CPU cgroup."""

import os
import sys
import time
from pathlib import Path

if sys.platform != "linux":
    raise RuntimeError("This diagnostic requires the reviewed Linux container")
if os.getuid() != 65532 or Path("/sys/fs/cgroup/cpu.max").read_text().strip() != "100000 100000":
    raise RuntimeError("The bounded nonroot container profile is required")

deadline = time.monotonic() + 40
while time.monotonic() < deadline:
    pass
