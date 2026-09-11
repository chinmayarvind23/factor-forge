"""Public immutable publication identity for the installer-free Python v2 runtime."""

import json
from typing import Any

PYTHON_REPOSITORY = "factorforge-python-runtime"
PYTHON_IMAGE = "sha256:d3f48bcda1df69a2e87baa63ab56d5883fa790e790c3c7b3c907dcc9097d57d4"
PYTHON_CONFIG = "sha256:f3418e6db48e622047d51483756f98a50346cb44f832e2b428a53f551192d3c3"
PYTHON_REFERENCE = PYTHON_REPOSITORY + "@" + PYTHON_IMAGE
PYTHON_ENV = (
    "PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG=C.UTF-8",
    "GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305",
    "PYTHON_VERSION=3.12.14",
    "PYTHON_SHA256=5c8462af5790baf43a321a1559dbe0db06d1be4300fb85fb53c40060668e548a",
)
ROOTFS_DIFF_IDS = (
    "sha256:34884abbe92863fce933ed7c39c0e045631af0ed86d5cc0dfbdf9fdca426ce3c",
    "sha256:3ca4be2c6e9ac0223715355253725381000486c2b45bfcb22cf571b6a85a12dd",
    "sha256:e5ccda0fbf6b54d343e024156d876553ba57d3926d7196584b3a1ce4df016366",
    "sha256:4098ad033525263f92a8a9c51865596025d47018e078c0b1f7d9cd5663fc1ffe",
    "sha256:09d75719de3f500dc0958f9f0511211b67699d0156e56c8c5666553417bbd1cc",
)


def matches_publication(actual: dict[str, Any]) -> bool:
    """Require containerd's full manifest and exact reviewed runtime fields without fallback.

    The config digest identifies the publication object; Docker's Config field is its runtime
    subset, not the raw config bytes. Comparing that subset and ordered diff IDs supplements
    the immutable manifest identity rather than claiming to recompute it from an inspect reply.
    """
    expected_config = {"Env": list(PYTHON_ENV), "Cmd": ["python3"], "WorkingDir": "/"}
    expected_rootfs = {"Type": "layers", "Layers": list(ROOTFS_DIFF_IDS)}
    try:
        descriptor = actual["Descriptor"]
        return bool(
            actual["Id"] == PYTHON_IMAGE
            and actual["RepoDigests"] == [PYTHON_REFERENCE]
            and actual["Os"] == "linux"
            and actual["Architecture"] == "amd64"
            and descriptor["digest"] == PYTHON_IMAGE
            and descriptor["mediaType"] == "application/vnd.oci.image.manifest.v1+json"
            and type(descriptor["size"]) is int
            and descriptor["size"] == 1033
            and json.dumps(actual["Config"], sort_keys=True, allow_nan=False)
            == json.dumps(expected_config, sort_keys=True)
            and json.dumps(actual["RootFS"], sort_keys=True, allow_nan=False)
            == json.dumps(expected_rootfs, sort_keys=True)
        )
    except (KeyError, TypeError, ValueError, RecursionError):
        return False
