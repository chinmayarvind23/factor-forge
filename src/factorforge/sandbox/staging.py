"""Verified temporary bind inputs exclude hostile containers, not privileged host processes."""

import ctypes
import hashlib
import json
import os
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from factorforge.data.artifacts import ArtifactStore, _Anchor, _directory
from factorforge.domain.errors import ResearchError
from factorforge.domain.experiments import ExperimentAdmission


@dataclass
class _Cleanup:
    """One teardown decision applies to every callback, preventing partial policy decisions."""

    enabled: bool = True


def _error(code: str = "SANDBOX_STAGING_FAILED") -> ResearchError:
    """Filesystem failures disclose neither private paths nor operating-system internals."""
    return ResearchError(code, "Experiment input staging is unavailable.", 503)


def _private_windows_directory(path: Path) -> None:
    """A protected owner/SYSTEM DACL supplies privacy that Windows chmod cannot express."""
    if sys.platform != "win32":
        raise RuntimeError("Windows directory security requires Windows")
    from ctypes import wintypes

    class SecurityAttributes(ctypes.Structure):
        """Pass an explicit noninherited protected descriptor during exclusive creation."""

        _fields_ = [
            ("length", wintypes.DWORD),
            ("descriptor", ctypes.c_void_p),
            ("inherit", wintypes.BOOL),
        ]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert.restype = wintypes.BOOL
    create = kernel.CreateDirectoryW
    create.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(SecurityAttributes)]
    create.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    if not convert("D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)", 1, ctypes.byref(descriptor), None):
        raise _error()
    try:
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        if not create(str(path), ctypes.byref(attributes)):
            raise _error()
    finally:
        kernel.LocalFree(descriptor)


def _identity(directory: _Anchor, name: str) -> tuple[int, int]:
    """Inspect the directory entry itself, so links never supply an owned object's identity."""
    if sys.platform == "win32":
        value = (directory.path / name).lstat()
    else:
        value = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
    if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
        raise _error("SANDBOX_STAGING_PATH_UNSAFE")
    return value.st_dev, value.st_ino


def _remove_directory(
    directory: _Anchor,
    name: str,
    identity: tuple[int, int],
    cleanup: _Cleanup,
) -> None:
    """Remove only the original now-empty owned directory, never a replacement or its target."""
    if not cleanup.enabled:
        return
    try:
        if _identity(directory, name) != identity:
            raise _error("SANDBOX_STAGING_CLEANUP")
        if sys.platform == "win32":
            (directory.path / name).rmdir()
        else:
            os.rmdir(name, dir_fd=directory.fd)
    except (OSError, ResearchError):
        raise _error("SANDBOX_STAGING_CLEANUP") from None


def _new_directory(
    stack: ExitStack,
    parent: _Anchor,
    name: str,
    cleanup: _Cleanup,
    *,
    private: bool,
) -> _Anchor:
    """Register cleanup only after exclusive creation, with pinned ancestors until removal."""
    path = parent.path / name
    if sys.platform == "win32":
        if private:
            _private_windows_directory(path)
        else:
            path.mkdir()
    else:
        os.mkdir(name, 0o700 if private else 0o755, dir_fd=parent.fd)
    identity = _identity(parent, name)
    stack.callback(_remove_directory, parent, name, identity, cleanup)
    anchor = stack.enter_context(_directory(path, create=False))
    if _identity(parent, name) != identity:
        raise _error("SANDBOX_STAGING_PATH_UNSAFE")
    if sys.platform != "win32":
        assert anchor.fd is not None
        opened = os.fstat(anchor.fd)
        if (opened.st_dev, opened.st_ino) != identity:
            raise _error("SANDBOX_STAGING_PATH_UNSAFE")
        os.fchmod(anchor.fd, 0o700 if private else 0o755)
    return anchor


def _remove_file(directory: _Anchor, name: str, descriptor: int, cleanup: _Cleanup) -> None:
    """A pinned file remains identifiable until its readonly flag is cleared and it is removed."""
    try:
        if not cleanup.enabled:
            return
        value = os.fstat(descriptor)
        if _identity(directory, name) != (value.st_dev, value.st_ino):
            raise _error("SANDBOX_STAGING_CLEANUP")
        if sys.platform == "win32":
            os.chmod(directory.path / name, stat.S_IREAD | stat.S_IWRITE)
    except (OSError, ResearchError):
        raise _error("SANDBOX_STAGING_CLEANUP") from None
    finally:
        os.close(descriptor)
    try:
        directory.remove_temporary(name)
    except OSError:
        raise _error("SANDBOX_STAGING_CLEANUP") from None


def _write(
    stack: ExitStack,
    directory: _Anchor,
    name: str,
    data: bytes,
    cleanup: _Cleanup,
) -> None:
    """Exclusive regular files retain handles through execution and flush before exposure."""
    descriptor = directory.open_file(name, create=True)
    stack.callback(_remove_file, directory, name, descriptor, cleanup)
    with os.fdopen(descriptor, "wb", closefd=False) as target:
        target.write(data)
        target.flush()
        os.fsync(descriptor)
    if sys.platform == "win32":
        os.chmod(directory.path / name, stat.S_IREAD)
    else:
        os.fchmod(descriptor, 0o444)


def _verified(admission: ExperimentAdmission, store: ArtifactStore) -> dict[str, bytes]:
    """Reread the bounded closure before filesystem work; receipts cannot attest later bytes."""
    result: dict[str, bytes] = {}
    for ref in admission.verified_refs:
        data = store.get(ref)
        if (
            type(data) is not bytes
            or len(data) != ref.size_bytes
            or hashlib.sha256(data).hexdigest() != ref.sha256
        ):
            raise ResearchError(
                "SANDBOX_ARTIFACT_INVALID",
                "Experiment artifact bytes are invalid.",
                422,
            )
        result[ref.sha256] = data
    return result


def _inventory(admission: ExperimentAdmission) -> bytes:
    """Fixed relative role paths bind the staged layout to the exact validated admission."""
    request = admission.spec
    value = {
        "schema_version": "experiment-input-inventory-v1",
        "admission_sha256": admission.sha256,
        "code": {"path": "code.py", "artifact": request.code.model_dump(mode="json")},
        "config": {"path": "config.json", "artifact": request.config.model_dump(mode="json")},
        "inputs": [
            {"path": "inputs/" + ref.sha256, "artifact": ref.model_dump(mode="json")}
            for ref in request.input_refs
        ],
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


@contextmanager
def staged_inputs(
    admission: ExperimentAdmission,
    store: ArtifactStore,
    *,
    parent: Path,
    cleanup_allowed: Callable[[], bool] | None = None,
) -> Iterator[Path]:
    """Expose a complete verified mount only for the lifetime of this context.

    The trusted server parent must already exist. A random private outer directory contains
    mount/code.py, config.json, inventory.json and inputs/<sha256>. POSIX outer permissions
    are 0700, mount/inputs 0755 and files 0444; Windows uses a protected owner/SYSTEM outer
    DACL and readonly files. Docker must independently mount this root readonly, retain the
    context through container cleanup, and verify actual effective runtime policy. The optional
    trusted cleanup_allowed callback is evaluated once at teardown: false retains every staged
    file/directory while closing handles. A callback failure also retains bytes and raises a
    typed cleanup error. Default cleanup removes the bundle. Retention needs later reconciliation.
    Privileged or same-account hostile host processes are outside this Path-based boundary.
    Cleanup failures remain typed and must not be reported as successful local cleanup.
    """
    try:
        receipt = ExperimentAdmission.model_validate(admission)
    except (ValueError, TypeError):
        raise ResearchError("SANDBOX_INPUT_INVALID", "Experiment input is invalid.", 422) from None
    data = _verified(receipt, store)
    cleanup = _Cleanup()
    with ExitStack() as stack:
        try:
            try:
                base = stack.enter_context(_directory(parent, create=False))
                private = _new_directory(
                    stack, base, "experiment-" + uuid4().hex, cleanup, private=True
                )
                mount = _new_directory(stack, private, "mount", cleanup, private=False)
                inputs = _new_directory(stack, mount, "inputs", cleanup, private=False)
                _write(stack, mount, "code.py", data[receipt.spec.code.sha256], cleanup)
                _write(stack, mount, "config.json", data[receipt.spec.config.sha256], cleanup)
                for digest in sorted({ref.sha256 for ref in receipt.spec.input_refs}):
                    _write(stack, inputs, digest, data[digest], cleanup)
                _write(stack, mount, "inventory.json", _inventory(receipt), cleanup)
            except OSError:
                raise _error() from None
            yield mount.path
        finally:
            if cleanup_allowed is not None:
                cleanup.enabled = False
                try:
                    decision = cleanup_allowed()
                    if type(decision) is not bool:
                        raise ValueError("Cleanup decision must be boolean")
                    cleanup.enabled = decision
                except Exception:
                    raise _error("SANDBOX_STAGING_CLEANUP") from None
