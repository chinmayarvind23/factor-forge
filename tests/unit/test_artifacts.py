"""Real filesystem tests verify immutable bytes and containment instead of mocking file access."""

import hashlib
import os
import subprocess
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pydantic import ValidationError

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Avoid pytest's convenience symlinks on Windows hosts that forbid their traversal."""
    with TemporaryDirectory(prefix="factorforge-artifact-") as directory:
        yield Path(directory)


def test_exact_bytes_roundtrip_and_concurrent_publication(tmp_path: Path) -> None:
    """Concurrent writers publish one complete immutable object and leave no temporary files."""
    store = LocalArtifactStore(tmp_path / "objects")
    data = b"original fixture\n"

    def publish(_: int) -> ArtifactRef:
        """Exercise independent handles and atomic filesystem publication."""
        return store.put(data, media_type="text/plain")

    with ThreadPoolExecutor(max_workers=8) as pool:
        refs = list(pool.map(publish, range(24)))
    assert all(ref == refs[0] for ref in refs)
    assert refs[0].sha256 == hashlib.sha256(data).hexdigest()
    assert store.get(refs[0]) == data
    assert len([path for path in (tmp_path / "objects").rglob("*") if path.is_file()]) == 1


def test_missing_tampered_and_truncated_objects_fail_closed(tmp_path: Path) -> None:
    """A digest-shaped path is never sufficient evidence that bytes are correct."""
    store = LocalArtifactStore(tmp_path)
    ref = store.put(b"abc")
    path = tmp_path / "sha256" / ref.sha256[:2] / ref.sha256
    path.write_bytes(b"abd")
    with pytest.raises(ResearchError) as corrupt:
        store.get(ref)
    assert corrupt.value.code == "ARTIFACT_INTEGRITY"
    with pytest.raises(ResearchError):
        store.put(b"abc")
    assert path.read_bytes() == b"abd"
    path.write_bytes(b"a")
    with pytest.raises(ResearchError):
        store.get(ref)
    path.unlink()
    with pytest.raises(ResearchError) as missing:
        store.get(ref)
    assert missing.value.code == "ARTIFACT_MISSING"


@pytest.mark.parametrize(
    "updates",
    [
        {"sha256": "../escape"},
        {"sha256": "A" * 64},
        {"size_bytes": -1},
        {"size_bytes": True},
        {"size_bytes": 2**30 + 1},
        {"media_type": ""},
        {"media_type": "text/plain\r\nInjected: yes"},
        {"url": "https://untrusted.example"},
    ],
)
def test_artifact_reference_rejects_untrusted_shape(updates: dict[str, object]) -> None:
    """References carry content identity, never caller-selected paths or remote locations."""
    with pytest.raises(ValidationError):
        ArtifactRef.model_validate(
            {
                "sha256": "0" * 64,
                "size_bytes": 0,
                "media_type": "application/octet-stream",
                **updates,
            }
        )


def test_object_size_limits_apply_before_io(tmp_path: Path) -> None:
    """Neither publication nor a metadata declaration can bypass the configured byte cap."""
    store = LocalArtifactStore(tmp_path, max_object_bytes=3)
    assert store.get(store.put(b"")) == b""
    assert store.get(store.put(b"abc")) == b"abc"
    with pytest.raises(ResearchError) as oversized:
        store.put(b"abcd")
    assert oversized.value.code == "ARTIFACT_TOO_LARGE"
    with pytest.raises(ResearchError):
        store.get(ArtifactRef(sha256="0" * 64, size_bytes=4, media_type="text/plain"))


def directory_link(link: Path, target: Path) -> None:
    """A Windows junction exercises reparse points even without symbolic-link privileges."""
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True
        )
        assert result.returncode == 0, "Could not create isolated junction fixture"
    else:
        link.symlink_to(target, target_is_directory=True)


def test_reparse_root_and_shard_cannot_escape(tmp_path: Path) -> None:
    """Pinning ancestor directories prevents existing symlinks/junctions from redirecting writes."""
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    directory_link(linked, outside)
    with pytest.raises(ResearchError) as unsafe:
        LocalArtifactStore(linked / "child")
    assert unsafe.value.code == "ARTIFACT_PATH_UNSAFE"
    assert not (outside / "child").exists()
    root = tmp_path / "objects"
    store = LocalArtifactStore(root)
    directory_link(root / "sha256", outside)
    with pytest.raises(ResearchError):
        store.put(b"cannot escape")
    assert list(outside.iterdir()) == []
    for link in (linked, root / "sha256"):
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()


@pytest.mark.parametrize("limit", [0, -1, True, 2**30 + 1])
def test_invalid_configured_limits_are_rejected(tmp_path: Path, limit: int) -> None:
    """Misconfiguration cannot silently remove an enforced object bound."""
    with pytest.raises(ValueError):
        LocalArtifactStore(tmp_path, max_object_bytes=limit)


def test_untrusted_constructed_ref_and_non_bytes_are_rejected(tmp_path: Path) -> None:
    """Bypassing Pydantic construction still cannot introduce a path to the store."""
    store = LocalArtifactStore(tmp_path)
    with pytest.raises(ValidationError):
        store.get(
            ArtifactRef.model_construct(sha256="../outside", size_bytes=0, media_type="text/plain")
        )
    with pytest.raises(TypeError):
        store.put("text")  # type: ignore[arg-type]
    ref = store.put(b"immutable")
    with pytest.raises(ValidationError):
        ref.size_bytes = 2


def test_failed_flush_never_publishes_partial_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A storage failure before publication removes only task-owned temporary content."""
    store = LocalArtifactStore(tmp_path)

    def failed_flush(_: int) -> None:
        """Inject a disk failure while the staging file exists."""
        raise OSError("sensitive host path")

    monkeypatch.setattr(os, "fsync", failed_flush)
    with pytest.raises(ResearchError) as failure:
        store.put(b"must not publish")
    assert failure.value.code == "ARTIFACT_IO"
    assert "sensitive" not in str(failure.value)
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_missing_shard_and_directory_leaf_are_typed(tmp_path: Path) -> None:
    """A missing ancestor and a non-file digest leaf fail without following another location."""
    store = LocalArtifactStore(tmp_path)
    ref = ArtifactRef(sha256="0" * 64, size_bytes=0, media_type="text/plain")
    with pytest.raises(ResearchError) as missing:
        store.get(ref)
    assert missing.value.code == "ARTIFACT_MISSING"
    leaf = tmp_path / "sha256" / "00" / ref.sha256
    leaf.mkdir(parents=True)
    with pytest.raises(ResearchError) as unsafe:
        store.get(ref)
    assert unsafe.value.code == "ARTIFACT_PATH_UNSAFE"


def test_symbolic_file_leaf_is_rejected(tmp_path: Path) -> None:
    """Opening a digest leaf must never follow a symbolic link even to matching bytes."""
    store = LocalArtifactStore(tmp_path / "objects")
    ref = store.put(b"abc")
    leaf = store.root / "sha256" / ref.sha256[:2] / ref.sha256
    leaf.unlink()
    outside = tmp_path / "external"
    outside.write_bytes(b"abc")
    leaf.symlink_to(outside)
    try:
        with pytest.raises(ResearchError) as unsafe:
            store.get(ref)
        assert unsafe.value.code == "ARTIFACT_PATH_UNSAFE"
        with pytest.raises(ResearchError):
            store.put(b"abc")
        assert outside.read_bytes() == b"abc"
    finally:
        leaf.unlink()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows handle ownership boundary")
def test_native_descriptor_transfer_failure_releases_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed native-to-Python handoff must not retain file or ancestor delete locks."""
    import msvcrt

    store = LocalArtifactStore(tmp_path / "objects")
    ref = store.put(b"abc")

    def failed_transfer(handle: int, flags: int) -> int:
        """Inject descriptor exhaustion after CreateFile has pinned the content file."""
        raise OSError("sensitive descriptor detail")

    with monkeypatch.context() as patch:
        patch.setattr(msvcrt, "open_osfhandle", failed_transfer)
        with pytest.raises(ResearchError) as failure:
            store.get(ref)
        assert failure.value.code == "ARTIFACT_IO"
        assert "sensitive" not in str(failure.value)
    assert store.get(ref) == b"abc"
    leaf = store.root / "sha256" / ref.sha256[:2] / ref.sha256
    leaf.unlink()
    store.root.rename(tmp_path / "renamed")
