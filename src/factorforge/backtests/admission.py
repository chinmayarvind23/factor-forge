"""Original monthly execution admits an exact, rights-checked snapshot of bounded source bytes."""

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from factorforge.data.artifacts import ArtifactStore, reference, verify_bytes
from factorforge.data.monthly_signals import load_monthly
from factorforge.data.raw_market import load_intervals, load_market
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.calendar import SessionCalendar
from factorforge.domain.datasets import DatasetManifest, ObservedDatasetManifest
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Digest
from factorforge.domain.monthly_signals import MonthlySourceBundle
from factorforge.domain.raw_market import IntervalSource, RawMarketSource
from factorforge.domain.raw_strategy import RawStrategySpec


def _fail(code: str = "MONTHLY_ADMISSION_INVALID") -> ResearchError:
    """Admission errors retain a stable reason without source values or storage diagnostics."""
    return ResearchError(code, "Monthly strategy source admission failed.", 422)


class AdmissionReceipt(Contract):
    """This metadata receipt documents byte admission, never completed economic execution."""

    schema_version: Literal["monthly-admission-v1"] = "monthly-admission-v1"
    profile: Literal["monthly-raw-price-post-fee-v1"] = "monthly-raw-price-post-fee-v1"
    scope: Literal["original-fixture-source-admission", "observed-source-admission"] = (
        "original-fixture-source-admission"
    )
    spec_sha256: Digest
    execution_sha256: Digest
    evaluated_at: AwareDatetime
    verified_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1, max_length=128)]
    manifest_version_ids: Annotated[tuple[Digest, ...], Field(min_length=1, max_length=8)]
    calendar_sha256: Digest
    monthly_ref: ArtifactRef
    market_ref: ArtifactRef
    intervals_ref: ArtifactRef

    @model_validator(mode="after")
    def closed_inventory(self) -> Self:
        """Receipt reload rejects repeated identities or role references absent from its closure."""
        refs = {ref.sha256: ref for ref in self.verified_refs}
        if tuple(refs) != tuple(sorted(refs)) or len(refs) != len(self.verified_refs):
            raise ValueError("Verified identities must be unique and sorted")
        versions = self.manifest_version_ids
        if versions != tuple(sorted(set(versions))) or not set(versions).issubset(refs):
            raise ValueError("Manifest identities must belong to the verified inventory")
        if self.calendar_sha256 not in refs or any(
            refs.get(ref.sha256) != ref
            for ref in (self.monthly_ref, self.market_ref, self.intervals_ref)
        ):
            raise ValueError("All source roles must belong to the verified inventory")
        if self.evaluated_at.utcoffset() != UTC.utcoffset(None):
            raise ValueError("Receipt clock must be normalized to UTC")
        return self


class VerifiedStore:
    """Execution rereads pinned input bytes; outputs still publish through the trusted provider."""

    def __init__(self, store: ArtifactStore, entries: dict[str, tuple[ArtifactRef, bytes]]) -> None:
        """Copy the verified inventory so caller dictionary mutations cannot replace inputs."""
        self._store = store
        self._entries = MappingProxyType(dict(entries))

    def get(self, ref: ArtifactRef) -> bytes:
        """No unlisted input can cause an additional provider read after source admission."""
        ref = ArtifactRef.model_validate(ref)
        entry = self._entries.get(ref.sha256)
        if entry is None or entry[0] != ref:
            raise _fail("MONTHLY_SOURCE_NOT_ADMITTED")
        return entry[1]

    def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """A provider cannot report publication under an unrelated identity or media type."""
        expected = reference(data, media_type, 64 * 1024 * 1024)
        observed = ArtifactRef.model_validate(self._store.put(data, media_type=media_type))
        if observed != expected:
            raise _fail("MONTHLY_OUTPUT_IDENTITY")
        return observed


@dataclass(frozen=True)
class MonthlyAdmission:
    """Runtime bundle is constructed on every public run, with no externally supplied grant."""

    spec: RawStrategySpec
    calendar: SessionCalendar
    monthly: MonthlySourceBundle
    market: RawMarketSource
    intervals: IntervalSource
    manifests: tuple[DatasetManifest, ...]
    receipt: AdmissionReceipt
    store: VerifiedStore


def _read(store: ArtifactStore, ref: ArtifactRef) -> bytes:
    """Successful storage responses still require a concrete byte type and independent digest."""
    try:
        raw = store.get(ArtifactRef.model_validate(ref).model_copy())
    except ResearchError:
        raise
    except Exception:
        raise _fail("MONTHLY_SOURCE_UNAVAILABLE") from None
    if type(raw) is not bytes:
        raise _fail("MONTHLY_SOURCE_INVALID")
    verify_bytes(raw, ref)
    return raw


def _manifests(
    spec: RawStrategySpec,
    store: ArtifactStore,
    at: datetime,
    entries: dict[str, tuple[ArtifactRef, bytes]],
) -> tuple[DatasetManifest, ...]:
    """All manifests and rights pass before calendar, declarations or market inputs are read."""
    coverage = spec.required_coverage()
    manifests = []
    tables = spec.table_references()
    for link in sorted(spec.datasets, key=lambda item: item.version_id):
        raw = _read(store, link.manifest)
        model = (
            ObservedDatasetManifest if spec.policies.dataset_kind == "observed" else DatasetManifest
        )
        manifest = model.model_validate_json(raw, strict=True)
        if manifest.version_id != link.version_id or manifest.canonical_bytes() != raw:
            raise _fail("MONTHLY_MANIFEST_IDENTITY")
        if not manifest.rights.permits("local_research", at):
            raise _fail("MONTHLY_DATA_USE_DENIED")
        if (
            manifest.kind != spec.policies.dataset_kind
            or manifest.retrieved_at > at
            or manifest.security_id_namespace != spec.universe.security_id_namespace
            or manifest.availability_policy
            != (
                "explicit-source-availability"
                if manifest.kind == "observed"
                else "explicit-authored-timestamps"
            )
            or manifest.universe_policy != "known-effective-events"
            or manifest.corporate_action_policy != "raw-prices-separate-explicit-actions"
            or manifest.delisting_policy != "explicit-exit-events-or-fail"
            or manifest.coverage_start > coverage[link.version_id]
            or manifest.coverage_end < spec.evaluation.sample_end
        ):
            raise _fail("MONTHLY_MANIFEST_POLICY")
        declared = {
            table.object_name: table for table in tables if table.dataset_version == link.version_id
        }
        objects = {item.name: item for item in manifest.objects}
        if set(objects) != set(declared):
            raise _fail("MONTHLY_MANIFEST_CLOSURE")
        for table in tables:
            if table.dataset_version != link.version_id:
                continue
            item = objects[table.object_name]
            if item.schema_version != table.schema_version or item.artifact != table.artifact:
                raise _fail("MONTHLY_TABLE_IDENTITY")
        entries[link.manifest.sha256] = (link.manifest, raw)
        manifests.append(manifest)
    return tuple(manifests)


def admit_monthly(
    spec: RawStrategySpec,
    store: ArtifactStore,
    *,
    evaluated_at: datetime,
) -> MonthlyAdmission:
    """Revalidate bounded metadata, rights and actual bytes before returning typed source roles.

    The caller supplies a trusted local store and assessment clock. Manifest rights are trusted
    ingestion declarations, not capabilities granted to remote users or model-generated text.
    Calendar scheduling and per-clock price/loan/comparison coverage remain execution gates.
    """
    try:
        if type(evaluated_at) is not datetime or evaluated_at.utcoffset() is None:
            raise ValueError("Assessment requires an aware datetime")
        at = evaluated_at.astimezone(UTC)
        spec = RawStrategySpec.model_validate(spec)
        refs = spec.unique_artifacts()
        entries: dict[str, tuple[ArtifactRef, bytes]] = {}
        manifests = _manifests(spec, store, at, entries)
        # Expand provenance only after all rights checks; preflight the combined budget before I/O.
        inventory = {ref.sha256: ref for ref in refs}
        for manifest in manifests:
            if isinstance(manifest, ObservedDatasetManifest):
                for derivation in manifest.derivations:
                    for ref in derivation.references():
                        if ref.sha256 in inventory and inventory[ref.sha256] != ref:
                            raise _fail("MONTHLY_EVIDENCE_CONFLICT")
                        inventory[ref.sha256] = ref
        if (
            len(inventory) > 128
            or sum(ref.size_bytes for ref in inventory.values()) > 64 * 1024 * 1024
        ):
            raise _fail("MONTHLY_EVIDENCE_LIMIT")
        refs = tuple(inventory[key] for key in sorted(inventory))
        for ref in refs:
            if ref.sha256 not in entries:
                entries[ref.sha256] = (ref, _read(store, ref))
        verified = VerifiedStore(store, entries)
        calendar_raw = verified.get(spec.timing.calendar)
        calendar = SessionCalendar.model_validate_json(calendar_raw, strict=True)
        if (
            calendar.canonical_bytes() != calendar_raw
            or calendar.calendar_id != spec.timing.calendar_id
        ):
            raise _fail("MONTHLY_CALENDAR_IDENTITY")
        monthly = load_monthly(spec.universe.table.artifact, verified)
        market = load_market(spec.market.table.artifact, verified)
        intervals = load_intervals(spec.evaluation.benchmark.table.artifact, verified)
        counts = {
            "monthly-source-v1": len(monthly.facts) + len(monthly.membership),
            "raw-market-source-v1": len(market.quotes)
            + len(market.actions)
            + len(market.borrow_grants),
            "interval-returns-v1": len(intervals.rows),
        }
        if any(
            item.row_count != counts[item.schema_version]
            for manifest in manifests
            for item in manifest.objects
        ):
            raise _fail("MONTHLY_SOURCE_ROW_COUNT")
        receipt = AdmissionReceipt(
            scope="observed-source-admission"
            if spec.policies.dataset_kind == "observed"
            else "original-fixture-source-admission",
            spec_sha256=spec.sha256,
            execution_sha256=spec.execution_sha256,
            evaluated_at=at,
            verified_refs=refs,
            manifest_version_ids=tuple(manifest.version_id for manifest in manifests),
            calendar_sha256=spec.timing.calendar.sha256,
            monthly_ref=spec.universe.table.artifact,
            market_ref=spec.market.table.artifact,
            intervals_ref=spec.evaluation.benchmark.table.artifact,
        )
        return MonthlyAdmission(
            spec, calendar, monthly, market, intervals, manifests, receipt, verified
        )
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise _fail() from None
