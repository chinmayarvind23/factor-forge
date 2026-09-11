"""Independent admission probes keep authorization and metadata distinct from runtime proof."""

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from test_experiments import IMAGE, OWNER, MemoryArtifacts, ref, result, spec

from factorforge.auth.principal import Principal
from factorforge.domain.errors import ResearchError
from factorforge.domain.experiments import ExperimentResult, ExperimentSpec, PythonSandboxPolicy
from factorforge.sandbox.policy import admit_experiment


class PermissivePrincipal(Principal):
    """A substituted authority method must not override verified capability fields."""

    def require(self, capability: str) -> None:
        """Deliberately grant everything to expose accidental dispatch to an untrusted override."""


def test_overridden_authority_method_cannot_grant_execution() -> None:
    """Admission reconstructs the principal instead of invoking its permissive method."""
    store = MemoryArtifacts()
    with pytest.raises(ResearchError, match="not permitted") as error:
        admit_experiment(
            spec(),
            store,
            principal=PermissivePrincipal(OWNER.issuer, OWNER.subject, frozenset()),
            image_digest=IMAGE,
            allowed_image_digests=frozenset({IMAGE}),
        )
    assert error.value.code == "FORBIDDEN" and store.reads == []


def test_owner_issuer_cannot_be_substituted_with_same_subject() -> None:
    """Subject equality across different issuers does not establish ownership."""
    store = MemoryArtifacts()
    with pytest.raises(ResearchError) as error:
        admit_experiment(
            spec(),
            store,
            principal=Principal("another-issuer", OWNER.subject, OWNER.capabilities),
            image_digest=IMAGE,
            allowed_image_digests=frozenset({IMAGE}),
        )
    assert error.value.code == "FORBIDDEN" and store.reads == []


def test_capability_check_precedes_invalid_request_or_image_inspection() -> None:
    """Denied principals cannot use artifact or validation behavior to inspect a request."""
    store = MemoryArtifacts()
    with pytest.raises(ResearchError) as error:
        admit_experiment(
            spec().model_copy(update={"seed": False}),
            store,
            principal=Principal(OWNER.issuer, OWNER.subject, frozenset()),
            image_digest=None,
            allowed_image_digests=frozenset(),
        )
    assert error.value.code == "FORBIDDEN" and store.reads == []


@pytest.mark.parametrize("field", ["code", "config", "input_refs"])
def test_forged_nested_artifact_is_rejected_before_io(field: str) -> None:
    """A frozen request copy cannot smuggle an invalid nested digest into storage."""
    store = MemoryArtifacts()
    bad = ref(b"{}").model_copy(update={"sha256": "../other"})
    request = spec().model_copy(update={field: (bad,) if field == "input_refs" else bad})
    with pytest.raises(ResearchError) as error:
        admit_experiment(
            request,
            store,
            principal=OWNER,
            image_digest=IMAGE,
            allowed_image_digests=frozenset({IMAGE}),
        )
    assert error.value.code == "SANDBOX_INPUT_INVALID" and store.reads == []


@pytest.mark.parametrize("image", [IMAGE + "\n", " " + IMAGE, IMAGE + ":tag", "repo@" + IMAGE])
def test_image_identity_has_no_whitespace_or_repository_alias(image: str) -> None:
    """Canonical identity is exact even when the same malformed string appears in the allowlist."""
    store = MemoryArtifacts()
    with pytest.raises(ResearchError) as error:
        admit_experiment(
            spec(),
            store,
            principal=OWNER,
            image_digest=image,
            allowed_image_digests=frozenset({image}),
        )
    assert error.value.code == "SANDBOX_UNAVAILABLE" and store.reads == []


@pytest.mark.parametrize("field,value", [("cpu_count", 1.0), ("read_only_inputs", 1)])
def test_json_security_controls_reject_numeric_aliases(field: str, value: object) -> None:
    """The JSON wire boundary preserves exact security boolean and integer types."""
    with pytest.raises(ValidationError):
        PythonSandboxPolicy.model_validate_json(json.dumps({field: value}))


@pytest.mark.parametrize("field", ["host_path", "mounts", "docker_endpoint", "entrypoint"])
def test_json_request_has_no_runtime_override_fields(field: str) -> None:
    """An accepted JSON request cannot carry a second execution configuration channel."""
    payload = spec().model_dump(mode="json") | {field: "untrusted"}
    with pytest.raises(ValidationError):
        ExperimentSpec.model_validate_json(json.dumps(payload))


def test_repeated_hour_uses_actual_utc_order() -> None:
    """A backward instant in a repeated local hour is invalid despite wall-clock ordering."""
    zone = ZoneInfo("America/New_York")
    start = datetime(2024, 11, 3, 1, 10, tzinfo=zone, fold=1)
    finish = datetime(2024, 11, 3, 1, 50, tzinfo=zone, fold=0)
    with pytest.raises(ValidationError):
        result(started_at=start, finished_at=finish)
    value = result(started_at=finish, finished_at=start)
    assert value.started_at == datetime(2024, 11, 3, 5, 50, tzinfo=UTC)
    assert value.finished_at == datetime(2024, 11, 3, 6, 10, tzinfo=UTC)


@pytest.mark.parametrize("field,value", [("launch_attempted", 1), ("oom_killed", 0)])
def test_json_result_observations_are_exact_booleans(field: str, value: object) -> None:
    """Numeric JSON aliases cannot supply an observed launch or non-OOM assertion."""
    payload = result().model_dump(mode="json") | {field: value}
    with pytest.raises(ValidationError):
        ExperimentResult.model_validate_json(json.dumps(payload))


def test_saved_result_identity_revalidates_forged_security_policy() -> None:
    """Canonical identity cannot bless a nested policy copy that disables input isolation."""
    value = result().model_copy(
        update={"policy": PythonSandboxPolicy().model_copy(update={"read_only_inputs": False})}
    )
    with pytest.raises(ValidationError):
        value.canonical_bytes()


def test_failed_create_with_confirmed_absence_needs_no_invented_container_id() -> None:
    """A create attempt can fail before identification and still have confirmed absence."""
    value = result(
        status="failed",
        container_id=None,
        exit_code=None,
        oom_killed=None,
        outputs=(),
        failure_code="CREATE_FAILED",
    )
    assert value.launch_attempted and value.cleanup == "confirmed"
    assert ExperimentResult.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize(
    "changes",
    [
        {"exit_code": 0},
        {"oom_killed": False},
        {"outputs": (ref(b"out"),)},
        {"status": "timed_out"},
        {"status": "cancelled"},
    ],
)
def test_unidentified_failed_create_cannot_invent_execution_observations(
    changes: dict[str, object],
) -> None:
    """The narrow create-failure case cannot weaken ordinary identified execution outcomes."""
    base: dict[str, object] = {
        "status": "failed",
        "container_id": None,
        "exit_code": None,
        "oom_killed": None,
        "outputs": (),
        "failure_code": "CREATE_FAILED",
    }
    with pytest.raises(ValidationError):
        result(**(base | changes))
