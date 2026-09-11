"""Deterministic hypothesis admission verifies declared contracts without running experiments."""

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, ValidationError, field_validator, model_validator

from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.datasets import DatasetManifest
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Digest, FactorSpec, Identifier

MAX_VERIFIED_BYTES = 64 * 1024 * 1024


class Hypothesis(Contract):
    """A source-backed draft can preserve uncertainty without pretending to be executable."""

    hypothesis_id: Identifier
    statement: Annotated[str, Field(min_length=1, max_length=2000)]
    mechanism: Annotated[str, Field(min_length=1, max_length=2000)]
    expected_direction: Literal["positive", "negative", "conditional"]
    source_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1, max_length=32)]
    factor_spec: FactorSpec | None
    unresolved_questions: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=500)], ...], Field(max_length=32)
    ]
    novelty: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    specificity: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]

    @model_validator(mode="after")
    def meaningful_uncertainty(self) -> Self:
        """Question placeholders cannot be blank or conceal portable-text failures."""
        if any(
            not question.strip() or not question.isprintable()
            for question in self.unresolved_questions
        ):
            raise ValueError("Unresolved questions must be meaningful and printable")
        return self


class QueueEntry(Contract):
    """Blocked and duplicate candidates remain visible in the hypothesis denominator."""

    hypothesis_id: Identifier
    hypothesis_sha256: Digest
    factor_sha256: Digest | None
    execution_sha256: Digest | None
    status: Literal["queued", "blocked", "duplicate"]
    blockers: Annotated[tuple[Identifier, ...], Field(max_length=32)]
    duplicate_of: Identifier | None
    ranking_score: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]

    @model_validator(mode="after")
    def coherent_status(self) -> Self:
        """Reloaded queue entries cannot claim admission while carrying blockers or absent
        identities."""
        if (self.factor_sha256 is None) != (self.execution_sha256 is None):
            raise ValueError("Factor and execution identities must agree on presence")
        if (self.status == "blocked") != bool(self.blockers):
            raise ValueError("Only blocked candidates carry blocker reasons")
        if (self.status == "duplicate") != (self.duplicate_of is not None):
            raise ValueError("Duplicate entries require an explicit retained candidate")
        if self.status != "blocked" and self.factor_sha256 is None:
            raise ValueError("Admitted candidates require complete factor identities")
        return self


class HypothesisQueue(Contract):
    """This is a planning queue; later row, engine, sandbox and budget gates still control
    execution."""

    schema_version: Literal["hypothesis-queue-v1"] = "hypothesis-queue-v1"
    ranking_version: Literal["novelty40-specificity30-testability30-v1"] = (
        "novelty40-specificity30-testability30-v1"
    )
    testability_scope: Literal["declared-contract-and-artifact-readiness"] = (
        "declared-contract-and-artifact-readiness"
    )
    input_sha256: Digest
    evaluated_at: AwareDatetime
    entries: Annotated[tuple[QueueEntry, ...], Field(min_length=1, max_length=64)]
    queued_ids: Annotated[tuple[Identifier, ...], Field(max_length=64)]

    @field_validator("evaluated_at")
    @classmethod
    def utc_assessment(cls, value: datetime) -> datetime:
        """Equivalent aware times identify the same recorded assessment instant."""
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent_inventory(self) -> Self:
        """The admission list and duplicate links must agree with the retained complete
        inventory."""
        entries = {entry.hypothesis_id: entry for entry in self.entries}
        if len(entries) != len(self.entries):
            raise ValueError("Queue entry identifiers must be unique")
        if self.queued_ids != tuple(
            entry.hypothesis_id for entry in self.entries if entry.status == "queued"
        ):
            raise ValueError("Queued identifiers do not match admitted entries")
        admitted = [entry.execution_sha256 for entry in self.entries if entry.status == "queued"]
        if len(set(admitted)) != len(admitted):
            raise ValueError("Admitted execution identities must be unique")
        for entry in self.entries:
            if entry.duplicate_of is not None:
                retained = entries.get(entry.duplicate_of)
                if (
                    retained is None
                    or retained.status != "queued"
                    or retained.execution_sha256 != entry.execution_sha256
                ):
                    raise ValueError(
                        "Duplicate reference must identify an admitted matching contract"
                    )
        return self


def _manifest_checks(spec: FactorSpec, store: ArtifactStore, at: datetime) -> list[str]:
    """After byte preflight, verify canonical identity, rights and declared table interpretation."""
    blockers: list[str] = []
    manifests: dict[str, DatasetManifest] = {}
    coverage = spec.required_coverage()
    security_versions = {
        spec.universe.table.dataset_version,
        spec.returns.table.dataset_version,
        *(binding.table.dataset_version for binding in spec.signal_inputs),
    }
    for link in spec.datasets:
        try:
            raw = store.get(link.manifest)
            manifest = DatasetManifest.model_validate_json(raw, strict=True)
            if manifest.version_id != link.version_id or manifest.canonical_bytes() != raw:
                blockers.append("manifest_identity_mismatch")
                continue
        except (ResearchError, ValueError):
            blockers.append("manifest_unavailable_or_invalid")
            continue
        manifests[link.version_id] = manifest
        if not manifest.rights.permits("local_research", at):
            blockers.append("dataset_use_not_permitted")
        if (
            link.version_id in security_versions
            and manifest.security_id_namespace != spec.universe.security_id_namespace
        ):
            blockers.append("security_id_namespace_mismatch")
        if manifest.availability_policy not in {
            "explicit-authored-timestamps",
            "explicit-publication-timestamps",
        }:
            blockers.append("unsupported_availability_policy")
        if (
            manifest.coverage_start > coverage[link.version_id]
            or manifest.coverage_end < spec.evaluation.sample_end
        ):
            blockers.append("insufficient_dataset_coverage")
    for table in spec.table_references():
        table_manifest = manifests.get(table.dataset_version)
        if table_manifest is None:
            continue
        objects = {item.name: item for item in table_manifest.objects}
        item = objects.get(table.object_name)
        if (
            item is None
            or item.schema_version != table.schema_version
            or item.artifact != table.artifact
        ):
            blockers.append("table_identity_mismatch")
    universe_manifest = manifests.get(spec.universe.table.dataset_version)
    if universe_manifest and universe_manifest.universe_policy != "known-effective-events":
        blockers.append("unsupported_universe_policy")
    returns_manifest = manifests.get(spec.returns.table.dataset_version)
    if returns_manifest and (
        returns_manifest.corporate_action_policy != "total-return-includes-actions-and-delisting"
        or returns_manifest.delisting_policy != "explicit-total-return-or-fail"
    ):
        blockers.append("unsupported_return_or_exit_policy")
    return blockers


def _assess(candidate: Hypothesis, store: ArtifactStore, at: datetime) -> tuple[str, ...]:
    """Readiness is a finite metadata/artifact gate, not empirical validation or an authorization
    grant."""
    blockers = []
    if candidate.unresolved_questions:
        blockers.append("unresolved_questions")
    if candidate.factor_spec is None:
        return tuple(sorted([*blockers, "missing_specification"]))
    spec = candidate.factor_spec
    references = [
        *candidate.source_refs,
        *spec.source_refs,
        spec.timing.calendar,
        *(link.manifest for link in spec.datasets),
        *(table.artifact for table in spec.table_references()),
    ]
    unique: dict[str, ArtifactRef] = {}
    for reference in references:
        if (
            reference.sha256 in unique
            and unique[reference.sha256].size_bytes != reference.size_bytes
        ):
            blockers.append("artifact_identity_conflict")
        unique[reference.sha256] = reference
    if sum(reference.size_bytes for reference in unique.values()) > MAX_VERIFIED_BYTES:
        blockers.append("artifact_verification_budget_exceeded")
    if blockers:
        return tuple(sorted(set(blockers)))
    blockers.extend(_manifest_checks(spec, store, at))
    if not blockers:
        for reference in unique.values():
            try:
                store.get(reference)
            except ResearchError:
                blockers.append("artifact_unavailable_or_corrupt")
    return tuple(sorted(set(blockers)))


def rank_hypotheses(
    candidates: Sequence[Hypothesis], store: ArtifactStore, *, at: datetime
) -> HypothesisQueue:
    """Apply fixed LLD weights, retain blockers and deduplicate exact executable choices before
    work."""
    try:
        if not isinstance(candidates, (list, tuple)) or not 1 <= len(candidates) <= 64:
            raise ValueError("Hypothesis inventory exceeds its bounds")
        if not isinstance(at, datetime) or at.utcoffset() is None:
            raise ValueError("An aware assessment time is required")
        validated = tuple(Hypothesis.model_validate(candidate) for candidate in candidates)
        if len({candidate.hypothesis_id for candidate in validated}) != len(validated):
            raise ValueError("Hypothesis identifiers must be unique")
    except (ValueError, ValidationError):
        raise ResearchError(
            "HYPOTHESIS_INVALID", "Hypothesis queue input is invalid.", 422
        ) from None
    assessed = [(candidate, _assess(candidate, store, at)) for candidate in validated]
    scored = [
        (
            candidate,
            blockers,
            math.fsum(
                (0.4 * candidate.novelty, 0.3 * candidate.specificity, 0.3 if not blockers else 0)
            ),
        )
        for candidate, blockers in assessed
    ]
    seen: dict[str, str] = {}
    entries = []
    for candidate, blockers, score in sorted(
        scored, key=lambda value: (-value[2], value[0].hypothesis_id)
    ):
        spec = candidate.factor_spec
        execution = spec.execution_sha256 if spec else None
        duplicate = seen.get(execution) if execution is not None and not blockers else None
        status: Literal["queued", "blocked", "duplicate"] = (
            "blocked" if blockers else "duplicate" if duplicate else "queued"
        )
        if status == "queued" and execution is not None:
            seen[execution] = candidate.hypothesis_id
        entries.append(
            QueueEntry(
                hypothesis_id=candidate.hypothesis_id,
                hypothesis_sha256=candidate.sha256,
                factor_sha256=spec.sha256 if spec else None,
                execution_sha256=execution,
                status=status,
                blockers=blockers,
                duplicate_of=duplicate,
                ranking_score=score,
            )
        )
    canonical_inputs = [
        candidate.model_dump(mode="json")
        for candidate in sorted(validated, key=lambda item: item.hypothesis_id)
    ]
    input_sha = hashlib.sha256(
        json.dumps(
            canonical_inputs,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    return HypothesisQueue(
        input_sha256=input_sha,
        evaluated_at=at.astimezone(UTC),
        entries=tuple(entries),
        queued_ids=tuple(entry.hypothesis_id for entry in entries if entry.status == "queued"),
    )
