"""Small original OCI layouts exercise identity, privacy and parser boundaries offline."""

import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from infra.sandbox.candidate.publication_oci import (
    Binding,
    PublicationError,
    _json,
    _publish,
    _read_archive,
    main,
    publish_archive,
)


def encode(value: object) -> bytes:
    """Use an independent stable JSON writer for the authored test objects."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value: bytes) -> str:
    """Bind the exact bytes supplied by each intentionally constructed fixture."""
    return hashlib.sha256(value).hexdigest()


def archive(rows: list[tuple[str, bytes]], *, link: bool = False) -> bytes:
    """Author a tiny tar directly, including malicious duplicate or link cases when requested."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as stream:
        for name, data in rows:
            item = tarfile.TarInfo(name)
            item.size = len(data)
            if link:
                item.type = tarfile.SYMTYPE
                item.linkname = "/outside"
                item.size = 0
            stream.addfile(item, io.BytesIO(data))
    return output.getvalue()


def fixture(
    *, labels: dict[str, str] | None = None, history: str = "trusted original test build"
) -> tuple[bytes, Binding]:
    """The small original filesystem is one gzip layer and has no real package or host data."""
    layer_raw = b"original authored layer bytes"
    layer = gzip.compress(layer_raw, mtime=0)
    config = encode(
        {
            "architecture": "amd64",
            "os": "linux",
            "config": {
                "Cmd": ["python3"],
                "Env": ["PATH=/usr/local/bin"],
                "WorkingDir": "/",
                "Labels": labels
                if labels is not None
                else {"private-test-label": "test-only-path"},
            },
            "rootfs": {"type": "layers", "diff_ids": ["sha256:" + digest(layer_raw)]},
            "history": [{"created_by": history}],
        }
    )
    manifest = encode(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": "sha256:" + digest(config),
                "size": len(config),
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "digest": "sha256:" + digest(layer),
                    "size": len(layer),
                }
            ],
        }
    )
    index = encode(
        {
            "schemaVersion": 2,
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": "sha256:" + digest(manifest),
                    "size": len(manifest),
                }
            ],
        }
    )
    raw = archive(
        [
            ("oci-layout", encode({"imageLayoutVersion": "1.0.0"})),
            ("index.json", index),
            *[("blobs/sha256/" + digest(value), value) for value in (manifest, config, layer)],
        ]
    )
    return raw, Binding(
        digest(raw), len(raw), digest(manifest), digest(config), ("private-test-label",)
    )


def test_publication_preserves_layers_runtime_and_history_but_removes_private_label() -> None:
    """Only the enumerated metadata change gets a new manifest; naming survives in both formats."""
    raw, binding = fixture()
    result, report = _publish(raw, binding)
    assert result == _publish(raw, binding)[0]
    files = _read_archive(result)
    index = json.loads(files["index.json"])
    descriptor = index["manifests"][0]
    assert (
        descriptor["annotations"]["org.opencontainers.image.ref.name"]
        == "factorforge-python-runtime:installer-free-v2"
    )
    assert descriptor["annotations"]["io.containerd.image.name"] == (
        "docker.io/library/factorforge-python-runtime@" + descriptor["digest"]
    )
    manifest = json.loads(files["blobs/sha256/" + descriptor["digest"][7:]])
    config = json.loads(files["blobs/sha256/" + manifest["config"]["digest"][7:]])
    assert config["config"] == {
        "Cmd": ["python3"],
        "Env": ["PATH=/usr/local/bin"],
        "WorkingDir": "/",
    }
    assert config["history"] == [{"created_by": "trusted original test build"}]
    assert "test-only-path" not in result.decode("latin1")
    assert report["source_sha256"] == binding.archive_sha256
    assert report["layers_unchanged"] is True
    assert report["history_unchanged"] is True
    assert report["publication_manifest_sha256"] != binding.manifest_sha256


def test_public_entry_accepts_only_pinned_source() -> None:
    """A self-consistent authored archive cannot replace the externally trusted original binding."""
    raw, _ = fixture()
    with pytest.raises(PublicationError):
        publish_archive(raw)


@pytest.mark.parametrize(
    "name", ["../outside", "/outside", "blobs/../outside", "C:/outside", "index.json\\evil"]
)
def test_unsafe_member_paths_fail(name: str) -> None:
    """The reader never extracts and rejects even syntactically redirected member names."""
    with pytest.raises(PublicationError):
        _read_archive(archive([(name, b"x")]))


def test_duplicate_members_and_links_fail() -> None:
    """A second name or symlink cannot conceal which bytes a later importer will see."""
    for raw in (
        archive([("index.json", b"{}"), ("index.json", b"{}")]),
        archive([("index.json", b"")], link=True),
    ):
        with pytest.raises(PublicationError):
            _read_archive(raw)


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_json", "wrong_descriptor_size", "unknown_label", "wrong_diff_id", "wrong_platform"],
)
def test_resigned_outer_archive_does_not_bypass_internal_validation(mutation: str) -> None:
    """Independent closure and shape checks operate beyond the outer archive checksum."""
    raw, binding = fixture(
        labels={"unexpected": "private"} if mutation == "unknown_label" else None
    )
    files = _read_archive(raw)
    if mutation == "duplicate_json":
        files["index.json"] = b'{"schemaVersion":2,"schemaVersion":2,"manifests":[]}'
    elif mutation == "wrong_descriptor_size":
        index = json.loads(files["index.json"])
        index["manifests"][0]["size"] += 1
        files["index.json"] = encode(index)
    elif mutation in {"wrong_diff_id", "wrong_platform"}:
        config = json.loads(files["blobs/sha256/" + binding.config_sha256])
        if mutation == "wrong_diff_id":
            config["rootfs"]["diff_ids"] = ["sha256:" + "0" * 64]
        else:
            config["architecture"] = "arm64"
        config_bytes = encode(config)
        manifest = json.loads(files.pop("blobs/sha256/" + binding.manifest_sha256))
        files.pop("blobs/sha256/" + binding.config_sha256)
        manifest["config"]["digest"] = "sha256:" + digest(config_bytes)
        manifest["config"]["size"] = len(config_bytes)
        manifest_bytes = encode(manifest)
        files["blobs/sha256/" + digest(config_bytes)] = config_bytes
        files["blobs/sha256/" + digest(manifest_bytes)] = manifest_bytes
        index = json.loads(files["index.json"])
        index["manifests"][0]["digest"] = "sha256:" + digest(manifest_bytes)
        index["manifests"][0]["size"] = len(manifest_bytes)
        files["index.json"] = encode(index)
        binding = Binding(
            binding.archive_sha256,
            binding.archive_size,
            digest(manifest_bytes),
            digest(config_bytes),
            binding.remove_labels,
        )
    changed = archive(list(files.items()))
    rebound = Binding(
        digest(changed),
        len(changed),
        binding.manifest_sha256,
        binding.config_sha256,
        binding.remove_labels,
    )
    with pytest.raises(PublicationError):
        _publish(changed, rebound)


@pytest.mark.parametrize(
    "data",
    [
        b'{"a":{"b":1,"b":2}}',
        b'{"a":NaN}',
        b'{"a":1.1}',
        b"[" * 22 + b"0" + b"]" * 22,
        encode(list(range(2050))),
        b'"' + b"x" * 65536 + b'"',
        b"\xff",
    ],
    ids=["duplicate", "nan", "float", "depth", "nodes", "length", "utf8"],
)
def test_json_ambiguity_types_and_bounds_fail(data: bytes) -> None:
    """No duplicate, noninteger numeric token, excessive shape or invalid UTF-8 gets interpreted."""
    with pytest.raises((PublicationError, UnicodeError)):
        _json(data)


def test_trailing_tar_payload_and_source_corruption_fail() -> None:
    """Appended archives and a single byte change cannot acquire a valid publication identity."""
    raw, binding = fixture()
    with pytest.raises(PublicationError):
        _read_archive(raw + archive([("index.json", b"{}")]))
    with pytest.raises(PublicationError):
        _publish(raw[:-1] + b"x", binding)


def test_layer_expansion_and_archive_size_have_hard_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid compressed object remains inadmissible when its expanded bytes exceed the cap."""
    raw, binding = fixture()
    monkeypatch.setattr("infra.sandbox.candidate.publication_oci.MAX_LAYER", 8)
    with pytest.raises(PublicationError):
        _publish(raw, binding)
    monkeypatch.setattr("infra.sandbox.candidate.publication_oci.MAX_ARCHIVE", 1024)
    with pytest.raises(PublicationError):
        _read_archive(raw)


@pytest.mark.parametrize(
    "history", [r"copy C:\Users\tester\source", "copy /home/tester/code", "copy /Users/tester/code"]
)
def test_private_history_is_rejected_instead_of_rewritten(history: str) -> None:
    """A source version with private historical commands needs a new enumerated transformation."""
    raw, binding = fixture(history=history)
    with pytest.raises(PublicationError):
        _publish(raw, binding)


def test_legitimate_shell_history_and_optional_index_type_remain_supported() -> None:
    """Raw string inspection does not mistake JSON quote escaping for a Windows drive path."""
    raw, binding = fixture(history='awk print "so:" package')
    files = _read_archive(raw)
    index = json.loads(files["index.json"])
    index["mediaType"] = "application/vnd.oci.image.index.v1+json"
    files["index.json"] = encode(index)
    changed = archive(list(files.items()))
    bound = Binding(
        digest(changed),
        len(changed),
        binding.manifest_sha256,
        binding.config_sha256,
        binding.remove_labels,
    )
    assert _publish(changed, bound)[1]["history_unchanged"] is True


def test_legacy_manifest_requires_the_same_complete_closure() -> None:
    """An importer cannot select a conflicting legacy image concealed beside valid OCI metadata."""
    raw, binding = fixture()
    files = _read_archive(raw)
    manifest = json.loads(files["blobs/sha256/" + binding.manifest_sha256])
    legacy = [
        {
            "Config": "blobs/sha256/" + binding.config_sha256,
            "RepoTags": None,
            "Layers": ["blobs/sha256/" + row["digest"][7:] for row in manifest["layers"]],
        }
    ]
    files["manifest.json"] = encode(legacy)
    valid = archive(list(files.items()))
    bound = Binding(
        digest(valid),
        len(valid),
        binding.manifest_sha256,
        binding.config_sha256,
        binding.remove_labels,
    )
    assert _publish(valid, bound)[1]["layers_unchanged"] is True
    legacy[0]["Layers"] = []
    files["manifest.json"] = encode(legacy)
    bad = archive(list(files.items()))
    rebound = Binding(
        digest(bad), len(bad), binding.manifest_sha256, binding.config_sha256, binding.remove_labels
    )
    with pytest.raises(PublicationError):
        _publish(bad, rebound)


def test_offline_cli_creates_exclusive_outputs_without_replacing_existing_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify bounded input first; a repeated invocation cannot overwrite existing evidence."""
    raw, binding = fixture()
    monkeypatch.setattr("infra.sandbox.candidate.publication_oci.ORIGINAL", binding)
    with TemporaryDirectory() as folder:
        root = Path(folder)
        source, output, report = [
            root / name for name in ("source.tar", "output.tar", "report.json")
        ]
        source.write_bytes(raw)
        monkeypatch.setattr(
            "sys.argv",
            [
                "publication_oci",
                "--source",
                str(source),
                "--output",
                str(output),
                "--report",
                str(report),
            ],
        )
        main()
        saved = output.read_bytes()
        assert json.loads(report.read_bytes())["publication_archive_sha256"] == digest(saved)
        with pytest.raises(FileExistsError):
            main()
        assert output.read_bytes() == saved
