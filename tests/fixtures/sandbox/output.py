"""Two MiB of finite output exceeds the combined one-MiB capture budget."""

import os
import sys

if sys.platform != "linux":
    raise RuntimeError("This diagnostic requires the reviewed Linux container")
if os.getuid() != 65532:
    raise RuntimeError("The nonroot container profile is required")

for _ in range(512):
    os.write(1, b"x" * 4096)
