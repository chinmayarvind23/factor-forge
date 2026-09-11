"""Admission checks authority and exact artifacts without granting container execution."""

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from factorforge.auth.principal import LOCAL_PRINCIPAL, Principal
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.experiments import (
    ExperimentAdmission,
    ExperimentResult,
    ExperimentSpec,
    PythonSandboxPolicy,
)
from factorforge.sandbox.policy import admit_experiment

IMAGE = "sha256:" + "a" * 64
OWNER = Principal("factorforge-local", "tester", frozenset({"execute_experiment"}))


def ref(data: bytes, media: str = "application/json") -> ArtifactRef:
    """Original bytes determine test identities independently of the admission implementation."""
    return ArtifactRef(
        sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), media_type=media
    )


class MemoryArtifacts:
    """Track every read so denied requests cannot inspect even a valid artifact."""

    def __init__(self) -> None:
        """Distinct code/config/data objects make deduplication and corruption observable."""
        self.data = {ref(raw).sha256: raw for raw in [b"print(1)", b"{}", b"[1]"]}
        self.reads: list[str] = []

    def get(self, reference: ArtifactRef) -> bytes:
        """The deliberately simple transport lets admission perform its own digest check."""
        self.reads.append(reference.sha256)
        return self.data[reference.sha256]

    def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Satisfy the store protocol without hiding any admission write in the fixture."""
        raise AssertionError("Admission must not write artifacts")


def spec(**changes: object) -> ExperimentSpec:
    """The internal request binds its owner and content, with no execution controls."""
    return ExperimentSpec.model_validate(
        {
            "experiment_id": UUID(int=1),
            "run_id": UUID(int=2),
            "owner_issuer": OWNER.issuer,
            "owner_subject": OWNER.subject,
            "factor_spec_sha256": "b" * 64,
            "code": ref(b"print(1)", "text/x-python"),
            "config": ref(b"{}"),
            "input_refs": (ref(b"[1]"),),
            "seed": 7,
            "engine": "python",
            "profile": "python-bounded-v1",
        }
        | changes
    )


def result(**changes: object) -> ExperimentResult:
    """A controller assertion is coherent metadata, never proof that this test launched Docker."""
    return ExperimentResult.model_validate(
        {
            "spec": spec(),
            "policy": PythonSandboxPolicy(),
            "image_digest": IMAGE,
            "status": "completed",
            "launch_attempted": True,
            "container_id": "c" * 64,
            "started_at": datetime(2024, 1, 1, tzinfo=UTC),
            "finished_at": datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC),
            "exit_code": 0,
            "oom_killed": False,
            "cleanup": "confirmed",
            "outputs": (ref(b"1", "text/plain"),),
            "failure_code": None,
        }
        | changes
    )


def test_admission_verifies_each_unique_identity_once_and_retains_fixed_policy() -> None:
    """Repeated references share verified bytes, while requested roles remain in the spec."""
    store = MemoryArtifacts()
    request = spec(input_refs=(ref(b"[1]"), ref(b"[1]"), ref(b"{}")))
    admitted = admit_experiment(
        request,
        store,
        principal=OWNER,
        image_digest=IMAGE,
        allowed_image_digests=frozenset({IMAGE}),
    )
    assert len(store.reads) == len(set(store.reads)) == 3
    assert admitted.verified_refs == request.unique_artifacts()
    assert admitted.spec == request and admitted.image_digest == IMAGE
    assert admitted.policy == PythonSandboxPolicy()
    assert admitted.scope == "verified-inputs-and-declared-policy-only"
    assert ExperimentAdmission.model_validate_json(admitted.model_dump_json()) == admitted


@pytest.mark.parametrize(
    "principal", [LOCAL_PRINCIPAL, Principal(OWNER.issuer, "other", OWNER.capabilities)]
)
def test_denied_owner_or_capability_never_reads_artifacts(principal: Principal) -> None:
    """Existing browser capabilities cannot imply experiment execution permission."""
    store = MemoryArtifacts()
    with pytest.raises(ResearchError) as error:
        admit_experiment(
            spec(),
            store,
            principal=principal,
            image_digest=IMAGE,
            allowed_image_digests=frozenset({IMAGE}),
        )
    assert error.value.code == "FORBIDDEN" and store.reads == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("issuer", " "),
        ("subject", 7),
        ("subject", "x" * 257),
        ("capabilities", {"execute_experiment"}),
        ("capabilities", frozenset({7})),
        ("issuer", "a\nb"),
    ],
)
def test_unvalidated_principal_dataclass_is_reconstructed_before_authority(
    field: str, value: object
) -> None:
    """Dataclass annotations alone cannot authorize malformed identities or mutable capabilities."""
    principal = Principal(OWNER.issuer, OWNER.subject, OWNER.capabilities)
    object.__setattr__(principal, field, value)
    store = MemoryArtifacts()
    with pytest.raises(ResearchError) as error:
        admit_experiment(
            spec(),
            store,
            principal=principal,
            image_digest=IMAGE,
            allowed_image_digests=frozenset({IMAGE}),
        )
    assert error.value.code == "FORBIDDEN" and not store.reads


@pytest.mark.parametrize(
    "image,allowed",
    [
        (None, frozenset({IMAGE})),
        (IMAGE, frozenset()),
        ("python:latest", frozenset({"python:latest"})),
        (IMAGE.upper(), frozenset({IMAGE.upper()})),
        (IMAGE, {IMAGE}),
    ],
)
def test_missing_or_untrusted_image_fails_without_fallback_or_reads(
    image: str | None, allowed: object
) -> None:
    """Even configured image identity must be immutable, canonical and explicitly allowlisted."""
    store = MemoryArtifacts()
    with pytest.raises(ResearchError) as error:
        admit_experiment(
            spec(),
            store,
            principal=OWNER,
            image_digest=image,
            allowed_image_digests=cast(frozenset[str], allowed),
        )
    assert error.value.code == "SANDBOX_UNAVAILABLE" and not store.reads


@pytest.mark.parametrize(
    "field,value",
    [
        ("seed", True),
        ("seed", 1.0),
        ("seed", -1),
        ("engine", "lean"),
        ("profile", "custom"),
        ("owner_issuer", ""),
        ("owner_subject", "\n"),
        ("image", IMAGE),
        ("argv", ["sh"]),
        ("environment", {"HOME": "/"}),
        ("network", "host"),
        ("input_refs", [ref(b"[1]")]),
    ],
)
def test_request_rejects_coercion_and_caller_execution_knobs(field: str, value: object) -> None:
    """The request schema cannot carry a hidden second path to execution settings."""
    with pytest.raises(ValidationError):
        spec(**{field: value})


def test_request_json_uuid_roundtrip_is_strict_and_immutable() -> None:
    """Portable UUID strings work in JSON while Python-mode strings do not bypass strict types."""
    value = spec()
    assert ExperimentSpec.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError):
        spec(run_id=str(value.run_id))
    with pytest.raises(ValidationError):
        value.seed = 8


@pytest.mark.parametrize(
    "kind",
    [
        "code",
        "config",
        "count",
        "aggregate",
        "conflict_size",
        "conflict_media",
        "code_media",
        "config_media",
    ],
)
def test_input_inventory_and_role_bounds_fail_before_work(kind: str) -> None:
    """Count unique bytes while rejecting contradictory metadata and wrong media roles."""
    value = spec()
    changes: dict[str, object] = {}
    if kind in {"code", "config"}:
        changes[kind] = getattr(value, kind).model_copy(update={"size_bytes": 256 * 1024 + 1})
    elif kind == "count":
        changes["input_refs"] = (ref(b"[1]"),) * 33
    elif kind == "aggregate":
        changes["input_refs"] = (ref(b"[1]").model_copy(update={"size_bytes": 16 * 1024 * 1024}),)
    elif kind == "conflict_size":
        changes["input_refs"] = (value.config.model_copy(update={"size_bytes": 3}),)
    elif kind == "conflict_media":
        changes["input_refs"] = (value.config.model_copy(update={"media_type": "text/plain"}),)
    else:
        field = kind.removesuffix("_media")
        changes[field] = getattr(value, field).model_copy(
            update={"media_type": "application/octet-stream"}
        )
    with pytest.raises(ValidationError):
        spec(**changes)


@pytest.mark.parametrize("corruption", [b"bad", b"[]", "{}"])
def test_preflight_rechecks_actual_bytes_from_the_store(corruption: object) -> None:
    """A protocol implementation cannot attest byte integrity merely by returning successfully."""
    store = MemoryArtifacts()
    store.data[ref(b"{}").sha256] = corruption  # type: ignore[assignment]
    with pytest.raises(ResearchError) as error:
        admit_experiment(
            spec(),
            store,
            principal=OWNER,
            image_digest=IMAGE,
            allowed_image_digests=frozenset({IMAGE}),
        )
    assert error.value.code == "SANDBOX_ARTIFACT_INVALID"


def test_copied_request_and_admission_are_revalidated() -> None:
    """Frozen-copy escape hatches cannot preserve valid admission or canonical identity."""
    store = MemoryArtifacts()
    with pytest.raises(ResearchError):
        admit_experiment(
            spec().model_copy(update={"seed": True}),
            store,
            principal=OWNER,
            image_digest=IMAGE,
            allowed_image_digests=frozenset({IMAGE}),
        )
    assert not store.reads
    admitted = admit_experiment(
        spec(), store, principal=OWNER, image_digest=IMAGE, allowed_image_digests=frozenset({IMAGE})
    )
    mutations: list[dict[str, object]] = [
        {"verified_refs": ()},
        {"policy": PythonSandboxPolicy().model_copy(update={"network": "host"})},
    ]
    for changes in mutations:
        with pytest.raises(ValidationError):
            admitted.model_copy(update=changes).canonical_bytes()


@pytest.mark.parametrize(
    "field,value",
    [
        ("cpu_count", True),
        ("memory_bytes", 1),
        ("pids_limit", 65),
        ("timeout_seconds", 31),
        ("tmpfs_bytes", 0),
        ("output_bytes", 2**21),
        ("network", "host"),
        ("read_only_root", 1),
        ("no_new_privileges", False),
        ("capabilities", ("SYS_ADMIN",)),
        ("uid", 0),
        ("docker_context", "default"),
    ],
)
def test_server_policy_cannot_disable_or_coerce_fixed_controls(field: str, value: object) -> None:
    """Literal validation must also reject bool/int aliases of fixed resource settings."""
    with pytest.raises(ValidationError):
        PythonSandboxPolicy.model_validate({field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"exit_code": 1},
        {"exit_code": True},
        {"oom_killed": True},
        {"oom_killed": None},
        {"cleanup": "unconfirmed"},
        {"container_id": None},
        {"image_digest": None},
        {"launch_attempted": False},
        {"failure_code": "BAD"},
        {"started_at": None},
        {"finished_at": datetime(2023, 1, 1, tzinfo=UTC)},
    ],
)
def test_completed_result_requires_coherent_controller_observations(
    changes: dict[str, object],
) -> None:
    """Success cannot hide failed execution, unknown cleanup or conflicting observations."""
    with pytest.raises(ValidationError):
        result(**changes)


def test_cleanup_unconfirmed_retains_observed_exit_without_becoming_complete() -> None:
    """Exit zero is compatible with failed cleanup and must not promote that outcome."""
    value = result(status="cleanup_unconfirmed", cleanup="unconfirmed", failure_code="DAEMON_LOST")
    assert value.exit_code == 0 and value.status == "cleanup_unconfirmed"
    assert value.scope == "controller-reported-outcome-not-independent-verification"
    assert ExperimentResult.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("status", ["failed", "unsupported"])
def test_prelaunch_failure_has_no_fabricated_runtime_observations(status: str) -> None:
    """An unavailable or unsupported profile can fail before any container exists."""
    value = result(
        status=status,
        launch_attempted=False,
        container_id=None,
        image_digest=None,
        started_at=None,
        exit_code=None,
        oom_killed=None,
        cleanup="not_started",
        outputs=(),
        failure_code="UNAVAILABLE",
    )
    assert not value.launch_attempted
    with pytest.raises(ValidationError):
        ExperimentResult.model_validate(value.model_copy(update={"exit_code": 0}))


def test_result_outputs_are_bounded_and_nested_observations_revalidate() -> None:
    """Controller metadata cannot hide excessive capture or an altered policy/spec after copying."""
    with pytest.raises(ValidationError):
        result(outputs=(ref(b"1").model_copy(update={"size_bytes": 2**20 + 1}),))
    value = result()
    with pytest.raises(ValidationError):
        value.model_copy(
            update={"spec": spec().model_copy(update={"seed": False})}
        ).canonical_bytes()


def test_nonprincipal_object_cannot_authorize_even_without_artifact_reads() -> None:
    """The runtime boundary checks dataclass identity rather than duck-typed authority methods."""
    store = MemoryArtifacts()
    with pytest.raises(ResearchError) as error:
        admit_experiment(
            spec(),
            store,
            principal=cast(Principal, object()),
            image_digest=IMAGE,
            allowed_image_digests=frozenset({IMAGE}),
        )
    assert error.value.code == "FORBIDDEN" and not store.reads


def test_admission_rejects_wrong_same_length_reference_closure() -> None:
    """A saved receipt cannot replace one input with a different apparently valid reference."""
    admitted = admit_experiment(
        spec(),
        MemoryArtifacts(),
        principal=OWNER,
        image_digest=IMAGE,
        allowed_image_digests=frozenset({IMAGE}),
    )
    with pytest.raises(ValidationError):
        ExperimentAdmission.model_validate(
            admitted.model_copy(
                update={"verified_refs": (admitted.spec.code, admitted.spec.config, ref(b"[9]"))}
            )
        )


@pytest.mark.parametrize("status", ["failed", "timed_out", "cancelled"])
def test_noncompleted_runtime_outcomes_keep_unknown_exit_observations(status: str) -> None:
    """Confirmed removal does not require inventing exit/OOM data lost before inspection."""
    value = result(status=status, exit_code=None, oom_killed=None, failure_code="STOPPED")
    assert value.cleanup == "confirmed" and value.exit_code is None
    with pytest.raises(ValidationError):
        ExperimentResult.model_validate(value.model_copy(update={"failure_code": None}))


def test_unconfirmed_cleanup_cannot_claim_confirmed_removal() -> None:
    """The status and attestation must agree even when exit zero was observed."""
    with pytest.raises(ValidationError):
        result(status="cleanup_unconfirmed", cleanup="confirmed", failure_code="DAEMON_LOST")


def test_utc_overflow_and_naive_observation_times_fail() -> None:
    """UTC conversion cannot leak platform overflow or silently assume a timezone."""
    for stamp in [datetime.min.replace(tzinfo=timezone(timedelta(hours=1))), datetime(2024, 1, 1)]:
        with pytest.raises(ValidationError):
            result(started_at=stamp)


def test_unique_inventory_accepts_exact_aggregate_limit_and_maximum_role_sizes() -> None:
    """Boundary inclusion and deduplication prevent accidental stricter limits than the contract."""
    value = spec()
    code = value.code.model_copy(update={"size_bytes": 256 * 1024})
    config = value.config.model_copy(update={"size_bytes": 256 * 1024})
    data = value.input_refs[0].model_copy(update={"size_bytes": 16 * 1024 * 1024 - 512 * 1024})
    boundary = spec(code=code, config=config, input_refs=(data,) * 32)
    assert sum(item.size_bytes for item in boundary.unique_artifacts()) == 16 * 1024 * 1024


def test_output_limit_counts_repeated_captures_and_accepts_exact_boundary() -> None:
    """Equal stream bytes still count twice toward the combined capture resource budget."""
    capture = ref(b"1", "text/plain").model_copy(update={"size_bytes": 512 * 1024})
    assert len(result(outputs=(capture, capture)).outputs) == 2
    with pytest.raises(ValidationError):
        result(outputs=(capture, capture, ref(b"x", "text/plain")))


@pytest.mark.parametrize(
    "allowed",
    [
        frozenset({IMAGE, "latest"}),
        frozenset({IMAGE, 5}),
        frozenset("sha256:" + f"{index:064x}" for index in range(33)),
    ],
)
def test_entire_allowlist_is_bounded_and_canonical(allowed: object) -> None:
    """A selected good image does not hide malformed server allowlist entries."""
    store = MemoryArtifacts()
    with pytest.raises(ResearchError) as error:
        admit_experiment(
            spec(),
            store,
            principal=OWNER,
            image_digest=IMAGE,
            allowed_image_digests=cast(frozenset[str], allowed),
        )
    assert error.value.code == "SANDBOX_UNAVAILABLE" and not store.reads
