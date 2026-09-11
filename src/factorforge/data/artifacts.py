"""Content-addressed local storage with pinned ancestors and no-overwrite atomic publication."""

import ctypes
import errno
import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from factorforge.domain.artifacts import MAX_ARTIFACT_BYTES, ArtifactRef
from factorforge.domain.errors import ResearchError

DEFAULT_OBJECT_LIMIT = 64 * 1024 * 1024
READ_CHUNK = 64 * 1024


class ArtifactStore(Protocol):
    """Catalogs depend on verified content operations rather than a storage-specific locator."""

    def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Publish exact bounded bytes or verify an already present identical object."""
        ...

    def get(self, ref: ArtifactRef) -> bytes:
        """Return bytes only after checking the requested content identity."""
        ...


def artifact_error(code: str, message: str, status: int = 409) -> ResearchError:
    """Filesystem/provider errors never expose host paths, bucket names or credentials."""
    return ResearchError(code, message, status)


def validate_limit(limit: int) -> None:
    """Configuration cannot disable the global object bound or accept booleans as limits."""
    if type(limit) is not int or not 0 < limit <= MAX_ARTIFACT_BYTES:
        raise ValueError("Object byte limit must be positive and within the global bound")


def reference(data: bytes, media_type: str, limit: int) -> ArtifactRef:
    """Validate size before hashing or opening storage; SHA-256 defines identity."""
    if not isinstance(data, bytes):
        raise TypeError("Artifact content must be bytes")
    if len(data) > limit:
        raise artifact_error("ARTIFACT_TOO_LARGE", "Artifact exceeds the byte limit.", 413)
    return ArtifactRef(
        sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), media_type=media_type
    )


def verify_bytes(data: bytes, ref: ArtifactRef) -> None:
    """Successful provider responses cannot replace exact length and digest checks."""
    if len(data) != ref.size_bytes or hashlib.sha256(data).hexdigest() != ref.sha256:
        raise artifact_error("ARTIFACT_INTEGRITY", "Artifact bytes do not match their reference.")


def _posix_flag(name: str) -> int:
    """Require POSIX containment flags without weakening unsupported-platform behavior."""
    return int(getattr(os, name))


def _windows_handle(path: Path, *, directory: bool, create: bool = False) -> int:
    """Deny deletion while pinned and inspect reparse metadata without following its target."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_handle = kernel.CreateFileW
    open_handle.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    open_handle.restype = wintypes.HANDLE
    access = 0 if directory else (0xC0000000 if create else 0x80000000)
    flags = 0x00200000 | 0x02000000
    handle = open_handle(str(path), access, 3, None, 1 if create else 3, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        code = ctypes.get_last_error()
        if code in {2, 3}:
            raise FileNotFoundError()
        if code in {80, 183}:
            raise FileExistsError()
        raise OSError(errno.EACCES, "Artifact handle unavailable")
    attributes = (wintypes.DWORD * 2)()
    query = kernel.GetFileInformationByHandleEx
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    query.restype = wintypes.BOOL
    try:
        if not query(handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)):
            raise OSError(errno.EACCES, "Artifact attributes unavailable")
        if attributes[0] & 0x400 or bool(attributes[0] & 0x10) != directory:
            raise artifact_error("ARTIFACT_PATH_UNSAFE", "Artifact storage path is unsafe.")
    except BaseException:
        _close_windows_handle(int(handle))
        if create:
            path.unlink(missing_ok=True)
        raise
    return int(handle)


def _close_windows_handle(handle: int) -> None:
    """Close each native handle unless a Python descriptor takes ownership."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle(handle)


@dataclass(frozen=True)
class _Anchor:
    """POSIX descriptors or pinned Windows ancestors keep later operations under the same root."""

    path: Path
    fd: int | None

    def open_file(self, name: str, *, create: bool = False) -> int:
        """Open the leaf without following links, and reject devices/directories before reading."""
        if os.name == "nt":
            import msvcrt

            handle = _windows_handle(self.path / name, directory=False, create=create)
            try:
                return msvcrt.open_osfhandle(
                    handle, os.O_BINARY | (os.O_RDWR if create else os.O_RDONLY)
                )
            except OSError:
                _close_windows_handle(handle)
                if create:
                    self.remove_temporary(name)
                raise
        flags = (
            _posix_flag("O_NOFOLLOW")
            | _posix_flag("O_NONBLOCK")
            | (os.O_RDWR | os.O_CREAT | os.O_EXCL if create else os.O_RDONLY)
        )
        descriptor = os.open(name, flags, 0o600, dir_fd=self.fd)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise artifact_error("ARTIFACT_PATH_UNSAFE", "Artifact leaf is not a regular file.")
        return descriptor

    def publish(self, temporary: str, digest: str) -> None:
        """Hard-link creation is atomic and fails if any destination already exists."""
        if os.name == "nt":
            os.link(self.path / temporary, self.path / digest, follow_symlinks=False)
        else:
            os.link(
                temporary, digest, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False
            )
            if self.fd is not None:
                os.fsync(self.fd)

    def remove_temporary(self, name: str) -> None:
        """Remove only the random task-owned staging name, never an existing content object."""
        if os.name == "nt":
            (self.path / name).unlink(missing_ok=True)
        else:
            with suppress(FileNotFoundError):
                os.unlink(name, dir_fd=self.fd)


@contextmanager
def _directory(path: Path, *, create: bool) -> Iterator[_Anchor]:
    """Pin every ancestor before creating children; no resolve-then-open race is trusted."""
    absolute = Path(os.path.abspath(path))
    with ExitStack() as stack:
        cursor = Path(absolute.anchor)
        descriptor: int | None = None
        for part in ("", *absolute.parts[1:]):
            cursor = cursor / part
            if os.name == "nt":
                try:
                    handle = _windows_handle(cursor, directory=True)
                except FileNotFoundError:
                    if not create:
                        raise
                    cursor.mkdir(exist_ok=True)
                    handle = _windows_handle(cursor, directory=True)
                stack.callback(_close_windows_handle, handle)
            else:
                try:
                    next_fd = os.open(
                        part or "/",
                        _posix_flag("O_DIRECTORY") | _posix_flag("O_NOFOLLOW"),
                        dir_fd=descriptor,
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    with suppress(FileExistsError):
                        os.mkdir(part, 0o700, dir_fd=descriptor)
                    next_fd = os.open(
                        part,
                        _posix_flag("O_DIRECTORY") | _posix_flag("O_NOFOLLOW"),
                        dir_fd=descriptor,
                    )
                descriptor = next_fd
                stack.callback(os.close, descriptor)
        yield _Anchor(absolute, descriptor)


class LocalArtifactStore:
    """Only digest-derived names are reachable; untrusted callers never supply filesystem paths."""

    def __init__(self, root: Path, *, max_object_bytes: int = DEFAULT_OBJECT_LIMIT) -> None:
        """Validate the allocated root before creating children or accepting content operations."""
        validate_limit(max_object_bytes)
        self.root = Path(os.path.abspath(root))
        self.max_object_bytes = max_object_bytes
        with self._safe_directory(self.root, create=True):
            pass

    @contextmanager
    def _safe_directory(self, path: Path, *, create: bool) -> Iterator[_Anchor]:
        """Expose stable typed errors while leaving paths and OS details private."""
        try:
            with _directory(path, create=create) as directory:
                yield directory
        except FileNotFoundError:
            raise artifact_error("ARTIFACT_MISSING", "Artifact is unavailable.", 404) from None
        except OSError as error:
            code = (
                "ARTIFACT_PATH_UNSAFE"
                if error.errno in {errno.ELOOP, errno.ENOTDIR}
                else "ARTIFACT_IO"
            )
            raise artifact_error(code, "Artifact storage operation failed.", 503) from None

    def _read(self, directory: _Anchor, ref: ArtifactRef) -> bytes:
        """Bound bytes independently of metadata before accepting the exact requested digest."""
        with os.fdopen(directory.open_file(ref.sha256), "rb") as source:
            data = source.read(ref.size_bytes + 1)
        verify_bytes(data, ref)
        return data

    def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Publish a flushed staging file without overwriting existing or corrupt content."""
        ref = reference(data, media_type, self.max_object_bytes)
        path = self.root / "sha256" / ref.sha256[:2]
        with self._safe_directory(path, create=True) as directory:
            temporary = ".pending-" + uuid4().hex
            # Cleanup ownership begins only after exclusive creation succeeds.
            descriptor = directory.open_file(temporary, create=True)
            try:
                with os.fdopen(descriptor, "wb") as target:
                    target.write(data)
                    target.flush()
                    os.fsync(target.fileno())
                    with suppress(FileExistsError):
                        directory.publish(temporary, ref.sha256)
                self._read(directory, ref)
            finally:
                directory.remove_temporary(temporary)
        return ref

    def get(self, ref: ArtifactRef) -> bytes:
        """Verify stored bytes on every access, including references supplied by a catalog."""
        ref = ArtifactRef.model_validate(ref)
        if ref.size_bytes > self.max_object_bytes:
            raise artifact_error("ARTIFACT_TOO_LARGE", "Artifact exceeds the byte limit.", 413)
        with self._safe_directory(self.root / "sha256" / ref.sha256[:2], create=False) as directory:
            return self._read(directory, ref)
