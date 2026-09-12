"""Dataset identity binds immutable timing, provenance and permitted-use metadata."""

import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from factorforge.domain.artifacts import ArtifactRef

Label = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
PermittedUse = Literal["local_research", "public_demo", "redistribution"]


def metadata_text(value: str) -> str:
    """Source descriptions remain meaningful single-line text in canonical UTF-8 metadata."""
    if not value.strip() or not value.isprintable():
        raise ValueError("Dataset metadata must contain nonblank printable text.")
    return value


class UsageRights(BaseModel):
    """Permissions are trusted ingestion metadata; unknown use rights grant nothing."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    provenance: str = Field(min_length=3, max_length=2000)
    terms_reference: str | None = Field(default=None, max_length=1000)
    permitted_uses: tuple[PermittedUse, ...] = ()
    retention_expires_at: AwareDatetime | None = None

    @field_validator("provenance", "terms_reference")
    @classmethod
    def readable_metadata(cls, value: str | None) -> str | None:
        """Unknown terms may be absent; present provenance or references must be readable."""
        return metadata_text(value) if value is not None else None

    @field_validator("permitted_uses")
    @classmethod
    def ordered_uses(cls, values: tuple[PermittedUse, ...]) -> tuple[PermittedUse, ...]:
        """Permission ordering has no meaning and must not perturb immutable identities."""
        return tuple(sorted(set(values)))

    @field_validator("retention_expires_at")
    @classmethod
    def utc_expiry(cls, value: datetime | None) -> datetime | None:
        """Equivalent provider offsets describe one retention deadline."""
        return value.astimezone(UTC) if value else None

    def permits(self, operation: PermittedUse, at: datetime) -> bool:
        """Expired retention disallows use even when the bytes remain in an object store."""
        if at.utcoffset() is None:
            return False
        return operation in self.permitted_uses and (
            self.retention_expires_at is None or at < self.retention_expires_at
        )


class DatasetObject(BaseModel):
    """Logical table names join exact byte identities to an explicit schema and row count."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    name: Label
    schema_version: Label
    row_count: Annotated[int, Field(strict=True, ge=0)]
    artifact: ArtifactRef


class DvcReference(BaseModel):
    """DVC's actual native digest is recorded independently from application SHA-256 hashes."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    git_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    pointer_path: str = Field(min_length=5, max_length=256)
    tool_version: str = Field(pattern=r"^3\.\d+\.\d+$")
    algorithm: Literal["md5"]
    digest: str = Field(pattern=r"^[a-f0-9]{32}(?:\.dir)?$")

    @field_validator("pointer_path")
    @classmethod
    def relative_pointer(cls, value: str) -> str:
        """References identify a repository pointer, never a host path or arbitrary URL."""
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or any(part in {".", ".."} for part in value.split("/"))
            or any(character in value for character in ("\\", ":", "\x00"))
            or not value.endswith(".dvc")
            or "//" in value
            or re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.dvc", value) is None
        ):
            raise ValueError("DVC pointers must be relative repository paths.")
        return value


class DatasetManifest(BaseModel):
    """Changing source, bytes or interpretation produces a new content-addressed version."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    schema_version: Literal["dataset-v1"] = "dataset-v1"
    name: Label
    kind: Literal["original_fixture", "observed"]
    provider: str = Field(min_length=1, max_length=128)
    source_version: Label
    retrieved_at: AwareDatetime
    coverage_start: date
    coverage_end: date
    security_id_namespace: Label
    universe_policy: Label
    availability_policy: Label
    corporate_action_policy: Label
    delisting_policy: Label
    rights: UsageRights
    objects: tuple[DatasetObject, ...] = Field(min_length=1, max_length=128)
    dvc: DvcReference | None = None

    @field_validator("provider")
    @classmethod
    def readable_provider(cls, value: str) -> str:
        """The provider label must not accept blank or control-bearing diagnostic content."""
        return metadata_text(value)

    @field_validator("retrieved_at")
    @classmethod
    def utc_snapshot(cls, value: datetime) -> datetime:
        """Canonical metadata cannot depend on which timezone wrote the snapshot."""
        return value.astimezone(UTC)

    @field_validator("objects")
    @classmethod
    def canonical_objects(cls, values: tuple[DatasetObject, ...]) -> tuple[DatasetObject, ...]:
        """An input table has one unambiguous reference regardless of ingestion order."""
        if len({value.name for value in values}) != len(values):
            raise ValueError("Dataset object names must be unique.")
        if sum(value.artifact.size_bytes for value in values) > 512 * 2**20:
            raise ValueError("This catalog slice accepts at most 512 MiB per dataset.")
        return tuple(sorted(values, key=lambda value: value.name))

    @model_validator(mode="after")
    def valid_coverage(self) -> "DatasetManifest":
        """Coverage cannot be reversed or extend beyond the recorded snapshot date."""
        if self.coverage_start > self.coverage_end or self.coverage_end > self.retrieved_at.date():
            raise ValueError("Dataset coverage must precede its snapshot.")
        return self

    def canonical_bytes(self) -> bytes:
        """Serialize only stable validated metadata; the identity itself is not self-referential."""
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()

    @property
    def version_id(self) -> str:
        """Content identity binds all declared policies and object references."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class ObservedDerivation(BaseModel):
    """Trusted ingestion records source bytes and transformation context for one normalized role."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    object_name: Label
    raw_sources: tuple[ArtifactRef, ...] = Field(min_length=1, max_length=16)
    normalizer: ArtifactRef
    parameters: ArtifactRef
    timing_evidence: ArtifactRef

    def references(self) -> tuple[ArtifactRef, ...]:
        """Archive code as evidence only; admission never executes a supplied normalizer."""
        return (*self.raw_sources, self.normalizer, self.parameters, self.timing_evidence)


class ObservedDatasetManifest(DatasetManifest):
    """Observed declarations require provenance beyond the normalized execution tables.

    Hash verification establishes retained identity, not the truth of provider timestamps
    or the correctness of normalization. Those remain trusted ingestion responsibilities.
    """

    kind: Literal["observed"] = "observed"
    observed_schema: Literal["observed-provenance-v1"] = "observed-provenance-v1"
    derivations: tuple[ObservedDerivation, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def complete_derivations(self) -> "ObservedDatasetManifest":
        """Each role has one derivation; identity transforms may share raw/output byte identity."""
        names = [row.object_name for row in self.derivations]
        objects = {row.name: row.artifact for row in self.objects}
        if len(set(names)) != len(names) or set(names) != set(objects):
            raise ValueError("Every observed object requires exactly one derivation")
        for row in self.derivations:
            if len({ref.sha256 for ref in row.raw_sources}) != len(row.raw_sources):
                raise ValueError("Raw source identities must be unique per derivation")
            if any(not 0 < ref.size_bytes <= 64 * 1024 * 1024 for ref in row.references()):
                raise ValueError("Observed evidence must be nonempty and bounded")
        return self


def parse_dataset_manifest(value: object) -> DatasetManifest:
    """Select the required observed contract without dropping subtype provenance in catalogs."""
    wire = value.model_dump() if isinstance(value, DatasetManifest) else value
    if not isinstance(wire, dict):
        raise ValueError("Dataset metadata requires an object")
    model = ObservedDatasetManifest if wire.get("kind") == "observed" else DatasetManifest
    return model.model_validate(wire)


def dataset_references(manifest: DatasetManifest) -> tuple[ArtifactRef, ...]:
    """Preflight the complete catalog inventory before touching source or transformation bytes."""
    references = [item.artifact for item in manifest.objects]
    if isinstance(manifest, ObservedDatasetManifest):
        references.extend(ref for row in manifest.derivations for ref in row.references())
    unique: dict[str, ArtifactRef] = {}
    for ref in references:
        if ref.sha256 in unique and unique[ref.sha256] != ref:
            raise ValueError("Dataset evidence has conflicting reference metadata")
        unique[ref.sha256] = ref
    limit = (64 if isinstance(manifest, ObservedDatasetManifest) else 512) * 1024 * 1024
    if len(unique) > 128 or sum(ref.size_bytes for ref in unique.values()) > limit:
        raise ValueError("Dataset evidence exceeds its inventory budget")
    return tuple(unique[key] for key in sorted(unique))
