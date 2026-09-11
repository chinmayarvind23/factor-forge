"""New runtime admission is exact while historical v1 declarations remain readable."""

import copy
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError
from test_experiments import IMAGE, OWNER, MemoryArtifacts, result, spec
from test_sandbox_docker_review import daemon_info, replies
from test_sandbox_docker_review import runtime as runtime

from factorforge.domain.errors import ResearchError
from factorforge.domain.experiments import ExperimentAdmission, ExperimentSpec, PythonSandboxPolicy
from factorforge.sandbox.docker import DockerRuntime
from factorforge.sandbox.policy import admit_experiment
from factorforge.sandbox.runner import run_experiment

MANIFEST = "sha256:d3f48bcda1df69a2e87baa63ab56d5883fa790e790c3c7b3c907dcc9097d57d4"
CONFIG = "sha256:f3418e6db48e622047d51483756f98a50346cb44f832e2b428a53f551192d3c3"
REPOSITORY = "factorforge-python-runtime"


def publication_image() -> dict[str, Any]:
    """Public immutable fields are transcribed from the reviewed sanitized publication receipt."""
    return {
        "Id": MANIFEST,
        "RepoDigests": [REPOSITORY + "@" + MANIFEST],
        "Os": "linux",
        "Architecture": "amd64",
        "Descriptor": {
            "digest": MANIFEST,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "size": 1033,
        },
        "Config": {
            "Env": [
                "PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "LANG=C.UTF-8",
                "GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305",
                "PYTHON_VERSION=3.12.14",
                "PYTHON_SHA256=5c8462af5790baf43a321a1559dbe0db06d1be4300fb85fb53c40060668e548a",
            ],
            "Cmd": ["python3"],
            "WorkingDir": "/",
        },
        "RootFS": {
            "Type": "layers",
            "Layers": [
                "sha256:34884abbe92863fce933ed7c39c0e045631af0ed86d5cc0dfbdf9fdca426ce3c",
                "sha256:3ca4be2c6e9ac0223715355253725381000486c2b45bfcb22cf571b6a85a12dd",
                "sha256:e5ccda0fbf6b54d343e024156d876553ba57d3926d7196584b3a1ce4df016366",
                "sha256:4098ad033525263f92a8a9c51865596025d47018e078c0b1f7d9cd5663fc1ffe",
                "sha256:09d75719de3f500dc0958f9f0511211b67699d0156e56c8c5666553417bbd1cc",
            ],
        },
    }


def test_historical_v1_canonical_record_remains_stable() -> None:
    """Adding an execution profile must not rewrite old spec or result serialization."""
    old = spec().canonical_bytes()
    assert ExperimentSpec.model_validate_json(old).canonical_bytes() == old
    archived = result().canonical_bytes()
    assert type(result()).model_validate_json(archived).canonical_bytes() == archived
    assert PythonSandboxPolicy().profile == "python-bounded-v1"


def test_v2_admission_records_matching_profile() -> None:
    """An explicitly required new profile binds verified bytes to the matching fixed policy."""
    store = MemoryArtifacts()
    accepted = admit_experiment(
        spec(profile="python-bounded-v2"),
        store,
        principal=OWNER,
        image_digest=IMAGE,
        allowed_image_digests=frozenset({IMAGE}),
        required_profile="python-bounded-v2",
    )
    assert accepted.policy.profile == accepted.spec.profile == "python-bounded-v2"
    assert len(store.reads) == 3


@pytest.mark.parametrize("required", ["python-bounded-v2", "unknown", True, None])
def test_profile_mismatch_or_invalid_server_profile_precedes_reads(required: object) -> None:
    """Legacy execution and malformed server configuration cannot inspect artifact contents."""
    store = MemoryArtifacts()
    with pytest.raises(ResearchError) as failure:
        admit_experiment(
            spec(),
            store,
            principal=OWNER,
            image_digest=IMAGE,
            allowed_image_digests=frozenset({IMAGE}),
            required_profile=cast(Any, required),
        )
    assert failure.value.code == "SANDBOX_PROFILE_UNSUPPORTED"
    assert store.reads == []


def test_admission_and_result_reject_mismatched_profiles() -> None:
    """Saved controller records cannot describe different request and enforcement profiles."""
    request = spec(profile="python-bounded-v2")
    with pytest.raises(ValidationError):
        ExperimentAdmission(
            spec=request,
            policy=PythonSandboxPolicy(),
            image_digest=IMAGE,
            verified_refs=request.unique_artifacts(),
        )
    with pytest.raises(ValidationError):
        result(spec=request)


def test_runner_rejects_legacy_before_store_or_runtime() -> None:
    """The production runner cannot execute v1 even though its historical records parse."""
    store = MemoryArtifacts()
    with pytest.raises(ResearchError) as failure:
        run_experiment(
            spec(),
            store,
            principal=OWNER,
            runtime=cast(DockerRuntime, object()),
            parent=Path("."),
            seccomp=Path("."),
        )
    assert failure.value.code == "SANDBOX_PROFILE_UNSUPPORTED" and not store.reads


def test_publication_preflight_requires_exact_manifest(
    runtime: DockerRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the sanitized image's full reviewed binding is accepted for new execution."""
    image = publication_image()
    calls = replies(runtime, monkeypatch, [daemon_info(), [image]])
    assert runtime.preflight(MANIFEST)["image"] == image
    assert calls[-1] == ("image", "inspect", REPOSITORY + "@" + MANIFEST)


@pytest.mark.parametrize(
    "section,key,value",
    [
        (None, "Id", CONFIG),
        (None, "Id", "sha256:" + "0" * 64),
        (None, "RepoDigests", ["python@" + MANIFEST]),
        (None, "Descriptor", None),
        (None, "RootFS", None),
        ("Descriptor", "digest", CONFIG),
        ("Descriptor", "size", 1034),
        ("Descriptor", "size", 1033.0),
        ("Descriptor", "size", True),
        ("Descriptor", "mediaType", "application/vnd.docker.distribution.manifest.v2+json"),
        ("Config", "User", "0"),
        ("Config", "Entrypoint", ["sh"]),
        ("Config", "Labels", {"unreviewed": "metadata"}),
        ("Config", "Healthcheck", {"Test": ["CMD", "sh"]}),
        ("Config", "Volumes", {"/input": {}}),
        ("Config", "WorkingDir", "/tmp"),
        ("Config", "Cmd", ["sh"]),
        ("Config", "Env", ["PYTHONPATH=/evil"]),
        ("RootFS", "Type", "unknown"),
        ("RootFS", "Layers", []),
    ],
)
def test_publication_binding_mutations_fail_closed(
    runtime: DockerRuntime,
    monkeypatch: pytest.MonkeyPatch,
    section: str | None,
    key: str,
    value: object,
) -> None:
    """Manifest, ordered filesystem and exact runtime config are separate required evidence."""
    image = publication_image()
    (image if section is None else image[section])[key] = copy.deepcopy(value)
    replies(runtime, monkeypatch, [daemon_info(), [image]])
    with pytest.raises(ResearchError) as failure:
        runtime.preflight(MANIFEST)
    assert failure.value.code == "SANDBOX_IMAGE_INVALID"


def test_ordered_rootfs_cannot_be_reordered(
    runtime: DockerRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An equal set of filesystem identities does not establish the same layer application."""
    image = publication_image()
    image["RootFS"]["Layers"].reverse()
    replies(runtime, monkeypatch, [daemon_info(), [image]])
    with pytest.raises(ResearchError):
        runtime.preflight(MANIFEST)
