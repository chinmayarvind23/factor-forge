"""Independent storage probes cover ownership cleanup and deadline completion boundaries."""

import hashlib
import os
import sys
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import cast

import pytest

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.s3_artifacts import S3ArtifactStore, S3Transport
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError


@pytest.fixture
def workspace() -> Iterator[Path]:
    """Use a real isolated directory without platform convenience symlinks."""
    with TemporaryDirectory(prefix="factorforge-storage-review-") as directory:
        yield Path(directory)


class Transport:
    """Supply one controlled response to test adapter cleanup without a network."""

    def __init__(self, body: object, size: int) -> None:
        """Retain the exact stream and declared size under review."""
        self.body = body
        self.size = size

    def get_object(self, **kwargs: object) -> dict[str, object]:
        """Expose the response through the normal object-read contract."""
        return {"Body": self.body, "ContentLength": self.size}


def remote(body: object, data: bytes) -> tuple[S3ArtifactStore, ArtifactRef]:
    """Keep content identity independent of the stream's behavior."""
    ref = ArtifactRef(
        sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), media_type="text/plain"
    )
    return (
        S3ArtifactStore(
            cast(S3Transport, Transport(body, len(data))), bucket="review-fixture", prefix="tests"
        ),
        ref,
    )


def test_failed_exclusive_create_keeps_preexisting_staging_file(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A collision must not let cleanup delete a staging file created by another operation."""
    store = LocalArtifactStore(workspace)
    digest = hashlib.sha256(b"new-content").hexdigest()
    shard = workspace / "sha256" / digest[:2]
    shard.mkdir(parents=True)
    pending = shard / ".pending-collision"
    pending.write_bytes(b"owned-by-another-writer")
    monkeypatch.setattr(
        "factorforge.data.artifacts.uuid4", lambda: SimpleNamespace(hex="collision")
    )
    with pytest.raises(ResearchError):
        store.put(b"new-content")
    assert pending.read_bytes() == b"owned-by-another-writer"
    assert not (shard / digest).exists()


def test_eof_after_deadline_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A slow final read cannot convert a timed-out operation into accepted bytes."""
    body = BytesIO(b"")
    store, ref = remote(body, b"")
    moments = iter([0.0, 0.0, 31.0])
    monkeypatch.setattr("factorforge.data.s3_artifacts.time.monotonic", lambda: next(moments))
    with pytest.raises(ResearchError) as failure:
        store.get(ref)
    assert failure.value.code == "ARTIFACT_IO"
    assert body.closed


def test_malformed_read_body_still_closes_available_connection() -> None:
    """Even an invalid read interface may own a connection that needs to be released."""
    stream = BytesIO()
    body = SimpleNamespace(close=stream.close)
    store, ref = remote(body, b"")
    with pytest.raises(ResearchError) as failure:
        store.get(ref)
    assert failure.value.code == "ARTIFACT_INTEGRITY"
    assert stream.closed


@pytest.mark.skipif(os.name != "nt", reason="Native handle transfer is Windows-specific")
def test_failed_native_creation_transfer_removes_owned_staging(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file created before descriptor transfer fails is still owned and must be cleaned up."""
    import msvcrt

    store = LocalArtifactStore(workspace)

    def reject_transfer(handle: int, flags: int) -> int:
        """Fail between successful native creation and Python descriptor ownership."""
        raise OSError("controlled transfer failure")

    with monkeypatch.context() as patch:
        patch.setattr(msvcrt, "open_osfhandle", reject_transfer)
        with pytest.raises(ResearchError):
            store.put(b"new-object")
    assert not list(workspace.rglob(".pending-*"))
    assert store.get(store.put(b"new-object")) == b"new-object"


@pytest.mark.skipif(os.name == "nt", reason="FIFO leaf probes require POSIX")
def test_fifo_leaf_fails_without_waiting_for_writer(workspace: Path) -> None:
    """Untrusted special files cannot turn a verified read into a blocking device operation."""
    store = LocalArtifactStore(workspace)
    digest = hashlib.sha256(b"").hexdigest()
    shard = workspace / "sha256" / digest[:2]
    shard.mkdir(parents=True)
    if sys.platform != "win32":
        os.mkfifo(shard / digest)
    ref = ArtifactRef(sha256=digest, size_bytes=0, media_type="text/plain")
    with pytest.raises(ResearchError) as failure:
        store.get(ref)
    assert failure.value.code == "ARTIFACT_PATH_UNSAFE"
