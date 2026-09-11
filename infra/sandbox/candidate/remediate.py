"""Offline candidate-only updates preserve package metadata and ensurepip functionality."""

import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

INPUTS = Path("/candidate-inputs")
APK_NAME = "libuuid-2.42.3-r1.apk"
WHEEL_NAME = "pip-26.2.1-py3-none-any.whl"
EXPECTED = {
    APK_NAME: "8306e5bb577696c9069fe1dfd9e1dcc39d2d481c6a1b0e707fd03c3e21aa6aa2",
    WHEEL_NAME: "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e",
}
ENSUREPIP_SHA256 = "90f6c76cd9ef7ed6daa198bb9ef771139683487f1b061211be7aa511831b2028"


def apk_inventory() -> dict[str, str]:
    """Reject unexpected util-linux-origin packages instead of broadening the update silently."""
    result = {}
    for block in Path("/lib/apk/db/installed").read_text().split("\n\n"):
        fields = dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
        if fields.get("o") == "util-linux":
            result[fields["P"]] = fields["V"]
    return result


def main() -> None:
    """Verify exact inputs, require Alpine signatures, and test the updated offline bootstrap."""
    for name, expected in EXPECTED.items():
        assert hashlib.sha256((INPUTS / name).read_bytes()).hexdigest() == expected
    assert sys.version_info[:3] == (3, 12, 14)
    assert apk_inventory() == {"libuuid": "2.42.1-r0"}
    ensurepip = Path("/usr/local/lib/python3.12/ensurepip")
    original = (ensurepip / "__init__.py").read_bytes()
    assert hashlib.sha256(original).hexdigest() == ENSUREPIP_SHA256
    old_wheel = ensurepip / "_bundled/pip-25.0.1-py3-none-any.whl"
    old_digest = hashlib.sha256(old_wheel.read_bytes()).hexdigest()
    # No trust bypass is permitted: the pinned base's Alpine keys verify this local APK.
    subprocess.run(
        [
            "/sbin/apk",
            "add",
            "--no-network",
            "--no-cache",
            "--repositories-file",
            "/dev/null",
            "--upgrade",
            str(INPUTS / APK_NAME),
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--no-compile",
            "--upgrade",
            str(INPUTS / WHEEL_NAME),
        ],
        check=True,
    )
    assert original.count(b'_PIP_VERSION = "25.0.1"') == 1
    updated = original.replace(b'_PIP_VERSION = "25.0.1"', b'_PIP_VERSION = "26.2.1"')
    shutil.copyfile(INPUTS / WHEEL_NAME, ensurepip / "_bundled" / WHEEL_NAME)
    (ensurepip / "__init__.py").write_bytes(updated)
    old_wheel.unlink()
    assert apk_inventory() == {"libuuid": "2.42.3-r1"}
    assert importlib.metadata.version("pip") == "26.2.1"
    # /tmp is a disposable build tmpfs, so the bootstrap test is not committed into the image.
    target = Path("/tmp/bootstrap-check")
    venv.EnvBuilder(with_pip=True, symlinks=True).create(target)
    result = subprocess.run(
        [
            str(target / "bin/python"),
            "-I",
            "-c",
            "import pip,ensurepip; assert pip.__version__ == ensurepip.version() == '26.2.1'",
        ],
        check=True,
    )
    assert result.returncode == 0
    print(
        json.dumps(
            {
                "libuuid": "2.42.3-r1",
                "pip": "26.2.1",
                "ensurepip": "26.2.1",
                "old_ensurepip_sha256": ENSUREPIP_SHA256,
                "new_ensurepip_sha256": hashlib.sha256(updated).hexdigest(),
                "old_bundled_wheel_sha256": old_digest,
                "offline_venv_bootstrap": "passed",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
