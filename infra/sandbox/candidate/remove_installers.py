"""Build an installer-free candidate by removing complete, explicitly inventoried components."""

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import venv
from pathlib import Path

APK = Path("/candidate-inputs/libuuid-2.42.3-r1.apk")
APK_SHA256 = "8306e5bb577696c9069fe1dfd9e1dcc39d2d481c6a1b0e707fd03c3e21aa6aa2"
ROOT = Path("/usr/local")
TREES = (
    ROOT / "lib/python3.12/site-packages/pip",
    ROOT / "lib/python3.12/site-packages/pip-25.0.1.dist-info",
    ROOT / "lib/python3.12/ensurepip",
)
ENTRYPOINTS = (ROOT / "bin/pip", ROOT / "bin/pip3", ROOT / "bin/pip3.12")


def trusted_path(path: Path, *, alias: bool = False) -> None:
    """Exact component roots and ordinary ancestors prevent removal through redirected paths."""
    assert path in (*TREES, *ENTRYPOINTS)
    assert path.is_relative_to(ROOT) and path != ROOT
    for parent in path.parents:
        assert not parent.is_symlink() and parent.is_dir()
    if alias:
        assert path.is_symlink() and os.readlink(path) == "pip3"
    else:
        assert not path.is_symlink()
        assert path.resolve(strict=True) == path


def inventory(path: Path) -> list[dict[str, object]]:
    """Record every removed file before deletion; reject links, special files and excess size."""
    result: list[dict[str, object]] = []
    total = 0
    for parent, directories, filenames in os.walk(path, followlinks=False):
        for name in sorted([*directories, *filenames]):
            item = Path(parent) / name
            info = item.lstat()
            assert not stat.S_ISLNK(info.st_mode)
            if stat.S_ISDIR(info.st_mode):
                continue
            assert stat.S_ISREG(info.st_mode)
            total += info.st_size
            assert total <= 32 * 1024 * 1024
            result.append(
                {
                    "path": str(item),
                    "size_bytes": info.st_size,
                    "sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
                }
            )
    return result


def util_linux_packages() -> dict[str, str]:
    """The source-family inventory must contain only the explicitly updated runtime library."""
    result = {}
    for block in Path("/lib/apk/db/installed").read_text().split("\n\n"):
        fields = dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
        if fields.get("o") == "util-linux":
            result[fields["P"]] = fields["V"]
    return result


def main() -> None:
    """Update the signed local APK, remove full installers, and verify a pip-free venv offline."""
    assert sys.version_info[:3] == (3, 12, 14)
    assert hashlib.sha256(APK.read_bytes()).hexdigest() == APK_SHA256
    assert util_linux_packages() == {"libuuid": "2.42.1-r0"}
    assert sorted(path.name for path in (ROOT / "bin").glob("pip*")) == ["pip", "pip3", "pip3.12"]
    records = []
    for path in TREES:
        trusted_path(path)
        assert path.is_dir()
        records.extend(inventory(path))
    for path in ENTRYPOINTS:
        alias = path.name == "pip"
        trusted_path(path, alias=alias)
        if alias:
            records.append({"path": str(path), "symlink_target": os.readlink(path)})
        else:
            assert stat.S_ISREG(path.lstat().st_mode)
            records.append(
                {
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    print(json.dumps({"removal_inventory": records}, sort_keys=True), flush=True)
    subprocess.run(
        [
            "/sbin/apk",
            "add",
            "--no-network",
            "--no-cache",
            "--repositories-file",
            "/dev/null",
            "--upgrade",
            str(APK),
        ],
        check=True,
    )
    # Only exact, fully inventoried roots are removed; package metadata is removed with its code.
    for path in TREES:
        shutil.rmtree(path)
    for path in ENTRYPOINTS:
        path.unlink()
    assert util_linux_packages() == {"libuuid": "2.42.3-r1"}
    assert importlib.util.find_spec("pip") is None
    assert importlib.util.find_spec("ensurepip") is None
    assert not list((ROOT / "bin").glob("pip*"))
    target = Path("/tmp/bootstrap-check")
    venv.EnvBuilder(with_pip=False, symlinks=True).create(target)
    subprocess.run(
        [
            str(target / "bin/python"),
            "-I",
            "-c",
            "import hashlib,pathlib,random,runpy,venv,importlib.util; "
            "assert importlib.util.find_spec('pip') is None; "
            "assert importlib.util.find_spec('ensurepip') is None",
        ],
        check=True,
    )
    print(
        json.dumps(
            {
                "libuuid": "2.42.3-r1",
                "pip": "removed",
                "ensurepip": "removed",
                "venv_without_pip": "passed",
                "removed_entries": len(records),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
