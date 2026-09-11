"""Declared experiment policy and controller records do not prove container containment."""

from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.factors import Contract, Digest, Identifier

CODE_CONFIG_LIMIT = 256 * 1024
INPUT_LIMIT = 16 * 1024 * 1024
OUTPUT_LIMIT = 1024 * 1024
ImageDigest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
PythonProfile = Literal["python-bounded-v1", "python-bounded-v2"]


def unique_refs(refs: tuple[ArtifactRef, ...]) -> tuple[ArtifactRef, ...]:
    """A digest has one size/media interpretation, while identical roles share one byte read."""
    found: dict[str, ArtifactRef] = {}
    for ref in refs:
        if ref.sha256 in found and found[ref.sha256] != ref:
            raise ValueError("Artifact identity has conflicting metadata")
        found[ref.sha256] = ref
    return tuple(found[key] for key in sorted(found))


class ExperimentSpec(Contract):
    """Internal ownership and artifact requests cannot select paths, environment or Docker flags."""

    schema_version: Literal["experiment-spec-v1"] = "experiment-spec-v1"
    experiment_id: UUID
    run_id: UUID
    owner_issuer: Annotated[str, Field(min_length=1, max_length=2048)]
    owner_subject: Annotated[str, Field(min_length=1, max_length=256)]
    factor_spec_sha256: Digest
    code: ArtifactRef
    config: ArtifactRef
    input_refs: Annotated[tuple[ArtifactRef, ...], Field(max_length=32)]
    seed: Annotated[int, Field(ge=0, le=2**32 - 1)]
    engine: Literal["python"]
    profile: PythonProfile

    @model_validator(mode="after")
    def bounded_inventory(self) -> Self:
        """Role limits and unique aggregate size apply before a store can allocate input bytes."""
        if (
            self.code.media_type != "text/x-python"
            or self.config.media_type != "application/json"
            or not 0 < self.code.size_bytes <= CODE_CONFIG_LIMIT
            or not 0 < self.config.size_bytes <= CODE_CONFIG_LIMIT
        ):
            raise ValueError("Code/config require bounded nonempty bytes and explicit role media")
        if (
            sum(ref.size_bytes for ref in unique_refs((self.code, self.config, *self.input_refs)))
            > INPUT_LIMIT
        ):
            raise ValueError("Unique input inventory exceeds its aggregate bound")
        return self

    def unique_artifacts(self) -> tuple[ArtifactRef, ...]:
        """Public inventory access revalidates copied instances before deduplicating references."""
        value = ExperimentSpec.model_validate(self)
        return unique_refs((value.code, value.config, *value.input_refs))


class PythonSandboxPolicy(Contract):
    """Only this fixed server profile is admitted; requested runtime overrides have no field."""

    profile: PythonProfile = "python-bounded-v1"
    cpu_count: Literal[1] = 1
    memory_bytes: Literal[536870912] = 536870912
    memory_swap_bytes: Literal[536870912] = 536870912
    pids_limit: Literal[64] = 64
    timeout_seconds: Literal[30] = 30
    tmpfs_bytes: Literal[67108864] = 67108864
    output_bytes: Literal[1048576] = 1048576
    uid: Literal[65532] = 65532
    gid: Literal[65532] = 65532
    network: Literal["none"] = "none"
    read_only_root: Literal[True] = True
    read_only_inputs: Literal[True] = True
    no_new_privileges: Literal[True] = True
    capabilities: Annotated[tuple[str, ...], Field(max_length=0)] = ()
    pid_namespace: Literal["private"] = "private"
    ipc_namespace: Literal["private"] = "private"
    seccomp: Literal["required"] = "required"
    tmpfs_options: Literal["nosuid,nodev,noexec"] = "nosuid,nodev,noexec"
    environment: Literal["server-fixed-no-inheritance"] = "server-fixed-no-inheritance"

    @field_validator(
        "cpu_count",
        "memory_bytes",
        "memory_swap_bytes",
        "pids_limit",
        "timeout_seconds",
        "tmpfs_bytes",
        "output_bytes",
        "uid",
        "gid",
        mode="before",
    )
    @classmethod
    def exact_integer(cls, value: object) -> object:
        """Pydantic Literal equality alone admits booleans and floating equivalents of integers."""
        if type(value) is not int:
            raise ValueError("Resource limits require exact integers")
        return value

    @field_validator("read_only_root", "read_only_inputs", "no_new_privileges", mode="before")
    @classmethod
    def exact_boolean(cls, value: object) -> object:
        """Fixed security booleans cannot be represented by numeric aliases."""
        if type(value) is not bool:
            raise ValueError("Security flags require exact booleans")
        return value


class ExperimentAdmission(Contract):
    """A validated byte/policy receipt is not runtime inspection or cryptographic attestation."""

    scope: Literal["verified-inputs-and-declared-policy-only"] = (
        "verified-inputs-and-declared-policy-only"
    )
    spec: ExperimentSpec
    policy: PythonSandboxPolicy
    image_digest: ImageDigest
    verified_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=2, max_length=34)]

    @model_validator(mode="after")
    def complete_references(self) -> Self:
        """Reloaded metadata must retain exactly the input closure that admission describes."""
        if self.policy.profile != self.spec.profile:
            raise ValueError("Admission policy must match the requested profile")
        if self.verified_refs != self.spec.unique_artifacts():
            raise ValueError("Admission references do not match its request")
        return self


class ExperimentResult(Contract):
    """Controller-reported terminal states preserve uncertainty instead of fabricating success."""

    scope: Literal["controller-reported-outcome-not-independent-verification"] = (
        "controller-reported-outcome-not-independent-verification"
    )
    spec: ExperimentSpec
    policy: PythonSandboxPolicy
    image_digest: ImageDigest | None
    status: Literal[
        "completed", "failed", "timed_out", "cancelled", "cleanup_unconfirmed", "unsupported"
    ]
    launch_attempted: bool
    container_id: Digest | None
    started_at: AwareDatetime | None
    finished_at: AwareDatetime
    exit_code: Annotated[int, Field(ge=0, le=255)] | None
    oom_killed: bool | None
    cleanup: Literal["not_started", "confirmed", "unconfirmed"]
    outputs: Annotated[tuple[ArtifactRef, ...], Field(max_length=32)]
    failure_code: Identifier | None

    @field_validator("started_at", "finished_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        """Normalize observation clocks before ordering, including repeated local wall times."""
        if value is None:
            return None
        try:
            return value.astimezone(UTC)
        except OverflowError:
            raise ValueError("Observation timestamp exceeds the UTC range") from None

    @model_validator(mode="after")
    def coherent_outcome(self) -> Self:
        """Validate assertions; only a future controller can supply runtime observations."""
        if self.policy.profile != self.spec.profile:
            raise ValueError("Result policy must match the requested profile")
        unique_refs(self.outputs)
        if sum(ref.size_bytes for ref in self.outputs) > OUTPUT_LIMIT:
            raise ValueError("Combined captured output exceeds the profile bound")
        if not self.launch_attempted:
            if (
                self.status not in {"failed", "unsupported"}
                or self.container_id is not None
                or self.started_at is not None
                or self.exit_code is not None
                or self.oom_killed is not None
                or self.cleanup != "not_started"
                or self.outputs
            ):
                raise ValueError("Prelaunch results cannot report container observations")
        else:
            if (
                self.image_digest is None
                or self.started_at is None
                or self.started_at > self.finished_at
                or self.status == "unsupported"
                or self.cleanup == "not_started"
            ):
                raise ValueError("Launch attempt requires image and ordered observation times")
            if self.status == "cleanup_unconfirmed":
                if self.cleanup != "unconfirmed":
                    raise ValueError("Unconfirmed cleanup cannot claim removal")
            elif self.cleanup != "confirmed":
                raise ValueError("Terminal execution requires confirmed cleanup")
            elif self.container_id is None and (
                self.status != "failed"
                or self.exit_code is not None
                or self.oom_killed is not None
                or self.outputs
            ):
                # A failed create may confirm nonce-owned absence without receiving an ID.
                raise ValueError("Unidentified create failure cannot report execution observations")
        if self.status == "completed":
            if self.exit_code != 0 or self.oom_killed is not False or self.failure_code is not None:
                raise ValueError("Completion requires zero exit, no OOM and no failure")
        elif self.failure_code is None:
            raise ValueError("Noncompleted outcome requires an explicit safe failure code")
        return self
