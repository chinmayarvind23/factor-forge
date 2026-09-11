"""An original parent-exit probe leaves one sleeping child for the private PID namespace."""

import json
import os
import sys
import time

if sys.platform != "linux":
    raise RuntimeError("This diagnostic requires the reviewed Linux container")
if os.getuid() != 65532:
    raise RuntimeError("The nonroot container profile is required")

child = os.fork()
if child == 0:
    time.sleep(20)
    os._exit(0)
print(json.dumps({"spawned_child": child}))
