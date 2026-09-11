"""Package one pinned candidate as a named OCI archive without executing or extracting it."""

import argparse
import copy
import gzip
import hashlib
import io
import json
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_ARCHIVE = 100 * 1024 * 1024
MAX_LAYER = 128 * 1024 * 1024
MAX_UNPACKED = 256 * 1024 * 1024
MAX_JSON = 64 * 1024
REPOSITORY = "factorforge-python-runtime"
TAG = REPOSITORY + ":installer-free-v2"
MANIFEST_TYPE = "application/vnd.oci.image.manifest.v1+json"
CONFIG_TYPE = "application/vnd.oci.image.config.v1+json"
LAYER_TYPE = "application/vnd.oci.image.layer.v1.tar+gzip"
HEX = re.compile(r"[a-f0-9]{64}\Z")


class PublicationError(ValueError):
    """A malformed or untrusted archive cannot produce an admitted publication candidate."""


@dataclass(frozen=True)
class Binding:
    """External identity pins are supplied by reviewed code, never by archive metadata."""

    archive_sha256: str
    archive_size: int
    manifest_sha256: str
    config_sha256: str
    remove_labels: tuple[str, ...]


ORIGINAL = Binding(
    "5310d8a94c75e4ba367478f5fb19711bd4f13d6498d9357798e312d5222b7d58",
    21228032,
    "b444379efe50b7166252872b4f62d0004e63953e8e4d49256448607ffbf6561c",
    "99703c29a69b0cc86c6bbca27b66e4fcebf339085411dccf9acb6e841a45efe2",
    (
        "desktop.docker.io/mounts/0/Source",
        "desktop.docker.io/mounts/0/SourceKind",
        "desktop.docker.io/mounts/0/Target",
        "desktop.docker.io/ports.scheme",
        "org.factorforge.controller-nonce",
    ),
)


def _require(condition: bool) -> None:
    """Boundary failures use one typed, non-sensitive diagnostic."""
    if not condition:
        raise PublicationError("OCI publication input failed strict validation")


def _sha(data: bytes) -> str:
    """Hash exact object bytes independently of their transport filename."""
    return hashlib.sha256(data).hexdigest()


def _encode(value: object) -> bytes:
    """Stable JSON changes only selected object serialization and explicit metadata."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous duplicate object keys at every JSON nesting level."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _json(data: bytes) -> Any:
    """Small UTF-8 metadata receives depth, node and duplicate-key limits before use."""
    _require(len(data) <= MAX_JSON)
    value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        _require(depth <= 20 and nodes <= 2048)
        _require(item is None or type(item) in (str, int, bool, list, dict))
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def _read_archive(raw: bytes) -> dict[str, bytes]:
    """Read bounded regular members only; never extract paths or accept hidden tar extensions."""
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE and len(raw) % 512 == 0)
    files: dict[str, bytes] = {}
    names: set[str] = set()
    end = 0
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            for member in archive:
                name = member.name.rstrip("/") if member.isdir() else member.name
                _require(name not in names and len(names) < 100 and not member.pax_headers)
                names.add(name)
                directory = member.isdir() and name in {"blobs", "blobs/sha256"}
                allowed = name in {"index.json", "oci-layout", "manifest.json"} or (
                    name.startswith("blobs/sha256/")
                    and HEX.fullmatch(name.removeprefix("blobs/sha256/")) is not None
                )
                _require(
                    directory or (member.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and allowed)
                )
                _require(member.offset_data == member.offset + 512)
                _require(0 <= member.size <= MAX_ARCHIVE)
                end = member.offset_data + ((member.size + 511) // 512) * 512
                if directory:
                    _require(member.size == 0)
                    continue
                total += member.size
                _require(total <= MAX_ARCHIVE)
                stream = archive.extractfile(member)
                _require(stream is not None)
                if stream is None:
                    raise PublicationError("Missing regular member stream")
                data = stream.read(member.size + 1)
                _require(len(data) == member.size)
                if name.startswith("blobs/"):
                    _require(_sha(data) == name.rsplit("/", 1)[1])
                files[name] = data
        _require(len(raw) - end >= 1024 and not any(raw[end:]))
        return files
    except (tarfile.TarError, OSError, EOFError, ValueError) as error:
        raise PublicationError("OCI archive is malformed or outside bounds") from error


def _object(files: dict[str, bytes], desc: Any, media_type: str) -> bytes:
    """Descriptor size and SHA-256 must agree before an object is interpreted."""
    _require(isinstance(desc, dict))
    _require(set(desc) <= {"mediaType", "digest", "size", "annotations", "platform"})
    _require(desc.get("mediaType") == media_type)
    digest = desc.get("digest")
    size = desc.get("size")
    _require(isinstance(digest, str) and digest.startswith("sha256:"))
    _require(HEX.fullmatch(digest[7:]) is not None)
    _require(type(size) is int and 0 < size <= MAX_ARCHIVE)
    value = files["blobs/sha256/" + digest[7:]]
    _require(len(value) == size and _sha(value) == digest[7:])
    return value


def _descriptor(data: bytes, media_type: str) -> dict[str, Any]:
    """A publication descriptor binds the newly serialized bytes exactly."""
    return {"mediaType": media_type, "digest": "sha256:" + _sha(data), "size": len(data)}


def _tar(files: dict[str, bytes]) -> bytes:
    """Emit deterministic plain USTAR files with no paths selected by the source archive."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(data))
    result = output.getvalue()
    _require(len(result) <= MAX_ARCHIVE)
    return result


def _publish(raw: bytes, binding: Binding) -> tuple[bytes, dict[str, Any]]:
    """The internal test seam still requires explicit trusted hashes for every authored fixture."""
    try:
        _require(len(raw) == binding.archive_size and _sha(raw) == binding.archive_sha256)
        files = _read_archive(raw)
        _require(_json(files["oci-layout"]) == {"imageLayoutVersion": "1.0.0"})
        index = _json(files["index.json"])
        _require(
            isinstance(index, dict)
            and set(index)
            in ({"schemaVersion", "manifests"}, {"schemaVersion", "manifests", "mediaType"})
        )
        _require(
            index.get("mediaType", "application/vnd.oci.image.index.v1+json")
            == "application/vnd.oci.image.index.v1+json"
        )
        _require(type(index["schemaVersion"]) is int and index["schemaVersion"] == 2)
        _require(isinstance(index["manifests"], list) and len(index["manifests"]) == 1)
        manifest_raw = _object(files, index["manifests"][0], MANIFEST_TYPE)
        _require(_sha(manifest_raw) == binding.manifest_sha256)
        manifest = _json(manifest_raw)
        _require(set(manifest) == {"schemaVersion", "mediaType", "config", "layers"})
        _require(type(manifest["schemaVersion"]) is int and manifest["schemaVersion"] == 2)
        _require(manifest["mediaType"] == MANIFEST_TYPE)
        config_raw = _object(files, manifest["config"], CONFIG_TYPE)
        _require(_sha(config_raw) == binding.config_sha256)
        config = _json(config_raw)
        _require(config["architecture"] == "amd64" and config["os"] == "linux")
        _require(set(config) <= {"architecture", "os", "created", "config", "rootfs", "history"})
        _require(isinstance(config["config"], dict) and isinstance(config["history"], list))
        rootfs = config["rootfs"]
        _require(set(rootfs) == {"type", "diff_ids"} and rootfs["type"] == "layers")
        layers = manifest["layers"]
        _require(isinstance(layers, list) and 1 <= len(layers) <= 16)
        _require(isinstance(rootfs["diff_ids"], list) and len(rootfs["diff_ids"]) == len(layers))
        output: dict[str, bytes] = {}
        expanded = 0
        for layer, diff_id in zip(layers, rootfs["diff_ids"], strict=True):
            blob = _object(files, layer, LAYER_TYPE)
            with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:
                unpacked = stream.read(MAX_LAYER + 1)
            expanded += len(unpacked)
            _require(len(unpacked) <= MAX_LAYER and expanded <= MAX_UNPACKED)
            _require(diff_id == "sha256:" + _sha(unpacked))
            output["blobs/sha256/" + _sha(blob)] = blob
        expected_names = {
            *output,
            "blobs/sha256/" + binding.config_sha256,
            "blobs/sha256/" + binding.manifest_sha256,
            "index.json",
            "oci-layout",
        }
        _require(set(files) in (expected_names, expected_names | {"manifest.json"}))
        if "manifest.json" in files:
            legacy = _json(files["manifest.json"])
            _require(isinstance(legacy, list) and len(legacy) == 1)
            _require(set(legacy[0]) == {"Config", "RepoTags", "Layers"})
            _require(legacy[0]["Config"] == "blobs/sha256/" + binding.config_sha256)
            _require(legacy[0]["RepoTags"] is None)
            _require(
                legacy[0]["Layers"] == ["blobs/sha256/" + layer["digest"][7:] for layer in layers]
            )
        original_config = copy.deepcopy(config)
        labels = config["config"].pop("Labels")
        _require(isinstance(labels, dict) and set(labels) == set(binding.remove_labels))
        # This exact original has no private history paths; reject unexpected ones instead of
        # rewriting historical commands with a broad, unverifiable text substitution.
        pending: list[Any] = [config]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str):
                _require(
                    re.search(
                        r"(?<![A-Za-z])[A-Za-z]:[\\/]|/Users/|/home/|desktop\.docker\.io", value
                    )
                    is None
                )
        new_config = _encode(config)
        new_config_desc = _descriptor(new_config, CONFIG_TYPE)
        manifest["config"] = new_config_desc
        new_manifest = _encode(manifest)
        new_desc = _descriptor(new_manifest, MANIFEST_TYPE)
        new_desc["annotations"] = {
            "org.opencontainers.image.ref.name": TAG,
            "io.containerd.image.name": "docker.io/library/"
            + REPOSITORY
            + "@sha256:"
            + _sha(new_manifest),
        }
        new_desc["platform"] = {"os": "linux", "architecture": "amd64"}
        output.update(
            {
                "blobs/sha256/" + _sha(new_config): new_config,
                "blobs/sha256/" + _sha(new_manifest): new_manifest,
                "oci-layout": _encode({"imageLayoutVersion": "1.0.0"}),
                "index.json": _encode({"schemaVersion": 2, "manifests": [new_desc]}),
                "manifest.json": _encode(
                    [
                        {
                            "Config": "blobs/sha256/" + _sha(new_config),
                            "RepoTags": [TAG],
                            "Layers": ["blobs/sha256/" + layer["digest"][7:] for layer in layers],
                        }
                    ]
                ),
            }
        )
        result = _tar(output)
        _read_archive(result)
        return result, {
            "schema_version": "candidate-oci-publication-v2",
            "repository": REPOSITORY,
            "tag": TAG,
            "source_sha256": binding.archive_sha256,
            "source_manifest_sha256": binding.manifest_sha256,
            "publication_manifest_sha256": _sha(new_manifest),
            "publication_config_sha256": _sha(new_config),
            "publication_archive_sha256": _sha(result),
            "publication_archive_size": len(result),
            "removed_label_names": sorted(binding.remove_labels),
            "layers_unchanged": True,
            "history_unchanged": config["history"] == original_config["history"],
            "runtime_fields_unchanged_except_removed_labels": True,
            "ordered_layer_digests": [layer["digest"] for layer in layers],
            "ordered_rootfs_diff_ids": rootfs["diff_ids"],
            "runtime_promoted": False,
        }
    except (KeyError, TypeError, ValueError, OSError, EOFError, RecursionError) as error:
        raise PublicationError("OCI publication failed; no image was executed") from error


def publish_archive(raw: bytes) -> tuple[bytes, dict[str, Any]]:
    """Only the exact reviewed original archive can enter the public publication utility."""
    return _publish(raw, ORIGINAL)


def main() -> None:
    """Produce new exclusive output files offline; never import, build, scan or run an image."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    with args.source.open("rb") as stream:
        raw = stream.read(MAX_ARCHIVE + 1)
    result, report = publish_archive(raw)
    with args.output.open("xb") as stream:
        stream.write(result)
    with args.report.open("xb") as stream:
        stream.write(_encode(report) + b"\n")


if __name__ == "__main__":
    main()
