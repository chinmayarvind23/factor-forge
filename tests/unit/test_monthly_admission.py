"""Admission verifies original source identities and rights before any economic input read."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from factorforge.data.artifacts import reference, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.raw_strategy import RawStrategySpec

AT = datetime(2026, 9, 11, 12, tzinfo=UTC)
FIXTURE = Path(__file__).resolve().parents[2] / "data/backtests/monthly-raw-v1/inputs"


class MemoryStore:
    """The deterministic test provider records actual reads and retains exact published bytes."""

    def __init__(self) -> None:
        """Every test starts with its own mutable provider, outside the immutable receipt."""
        self.values: dict[str, bytes] = {}
        self.reads: list[str] = []

    def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Use real content identities while keeping filesystem behavior out of scope."""
        ref = reference(data, media_type, 64 * 1024 * 1024)
        self.values[ref.sha256] = data
        return ref

    def get(self, ref: ArtifactRef) -> bytes:
        """Record provider access even when its claimed object has become corrupt."""
        self.reads.append(ref.sha256)
        return self.values[ref.sha256]


def original_strategy() -> tuple[RawStrategySpec, MemoryStore]:
    """Bind a complete v3 declaration to original input bytes without reading expected outputs."""
    store = MemoryStore()
    for name in ("calendar", "signals", "market", "intervals", "manifest", "input-freeze"):
        store.put((FIXTURE / f"{name}.json").read_bytes(), media_type="application/json")
    spec = RawStrategySpec.model_validate_json((FIXTURE.parent / "strategy.json").read_bytes())
    return spec, store


def changed_manifest(
    spec: RawStrategySpec, store: MemoryStore, **changes: object
) -> RawStrategySpec:
    """Publish new canonical metadata and update every version link without changing input bytes."""
    from factorforge.domain.datasets import DatasetManifest

    value = json.loads(store.values[spec.datasets[0].manifest.sha256])
    value.update(changes)
    manifest = DatasetManifest.model_validate_json(json.dumps(value))
    ref = store.put(manifest.canonical_bytes(), media_type="application/json")
    wire = spec.model_dump(mode="json")
    old = spec.datasets[0].version_id
    wire["datasets"] = [{"version_id": ref.sha256, "manifest": ref.model_dump()}]
    for binding in [
        wire["universe"],
        wire["market"],
        *wire["signal_inputs"],
        wire["evaluation"]["benchmark"],
        wire["evaluation"]["risk_free"],
    ]:
        assert binding["table"]["dataset_version"] == old
        binding["table"]["dataset_version"] = ref.sha256
    return RawStrategySpec.model_validate_json(json.dumps(wire))


def test_original_admission_binds_verified_closure_and_snapshots_provider() -> None:
    """A later corrupt provider cannot change source bytes retained by a successful admission."""
    from factorforge.backtests.admission import admit_monthly

    spec, store = original_strategy()
    admitted = admit_monthly(spec, store, evaluated_at=AT)
    assert admitted.receipt.spec_sha256 == spec.sha256
    assert admitted.receipt.execution_sha256 == spec.execution_sha256
    assert admitted.calendar.calendar_id == spec.timing.calendar_id
    assert len(admitted.monthly.facts) == 3 and len(admitted.market.quotes) == 16
    assert len(store.reads) == len(set(store.reads)) == 6
    assert admitted.receipt.verified_refs == spec.unique_artifacts()
    ref = spec.market.table.artifact
    before = store.values[ref.sha256]
    store.values[ref.sha256] = b"corrupt"
    assert admitted.store.get(ref) == before
    output = admitted.store.put(b"retained execution")
    verify_bytes(store.values[output.sha256], output)


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "observed"},
        {"security_id_namespace": "other-v1"},
        {"availability_policy": "unknown"},
        {"universe_policy": "current-only"},
        {"corporate_action_policy": "adjusted-prices"},
        {"delisting_policy": "ignore"},
        {"coverage_start": "2024-04-30"},
        {"coverage_end": "2024-05-02"},
        {"rights": {"provenance": "unknown rights", "permitted_uses": []}},
    ],
)
def test_incompatible_manifest_stops_before_economic_source_reads(
    change: dict[str, object],
) -> None:
    """Exact metadata hashes do not grant use rights or silently reinterpret its source policy."""
    from factorforge.backtests.admission import admit_monthly

    spec, store = original_strategy()
    spec = changed_manifest(spec, store, **change)
    with pytest.raises(ResearchError):
        admit_monthly(spec, store, evaluated_at=AT)
    assert store.reads == [spec.datasets[0].manifest.sha256]


@pytest.mark.parametrize(
    "target", ["manifest", "calendar", "signals", "market", "intervals", "input-freeze"]
)
def test_provider_success_cannot_replace_hash_verification(target: str) -> None:
    """Every source and declaration reference is independently checked after provider return."""
    from factorforge.backtests.admission import admit_monthly

    spec, store = original_strategy()
    original = (FIXTURE / f"{target}.json").read_bytes()
    ref = reference(original, "application/json", 64 * 1024 * 1024)
    store.values[ref.sha256] = b"false provider success"
    with pytest.raises(ResearchError) as caught:
        admit_monthly(spec, store, evaluated_at=AT)
    assert caught.value.code == "ARTIFACT_INTEGRITY"


@pytest.mark.parametrize("at", [datetime(2026, 9, 11), None, True])
def test_invalid_clock_stops_before_storage(at: object) -> None:
    """A trusted assessment time must be explicit and aware before retention rights are checked."""
    from factorforge.backtests.admission import admit_monthly

    spec, store = original_strategy()
    with pytest.raises(ResearchError):
        admit_monthly(spec, store, evaluated_at=at)  # type: ignore[arg-type]
    assert store.reads == []


def test_conflicting_object_roles_cannot_be_overwritten_by_dictionary_order() -> None:
    """Two table roles with one object name must not discard one schema or byte interpretation."""
    from factorforge.backtests.admission import admit_monthly

    spec, store = original_strategy()
    wire = spec.model_dump(mode="json")
    wire["market"]["table"]["object_name"] = "signals"
    spec = RawStrategySpec.model_validate_json(json.dumps(wire))
    manifest = json.loads(store.values[spec.datasets[0].manifest.sha256])
    manifest["objects"] = [item for item in manifest["objects"] if item["name"] != "market"]
    spec = changed_manifest(spec, store, objects=manifest["objects"])
    with pytest.raises(ResearchError) as caught:
        admit_monthly(spec, store, evaluated_at=AT)
    assert caught.value.code == "MONTHLY_TABLE_IDENTITY"
    assert store.reads == [spec.datasets[0].manifest.sha256]


@pytest.mark.parametrize("case", ["extra", "count", "schema", "bytes", "expired", "future"])
def test_manifest_inventory_and_retention_are_enforced(case: str) -> None:
    """Manifest identity cannot hide unverified objects, false row counts or expired rights."""
    from factorforge.backtests.admission import admit_monthly

    spec, store = original_strategy()
    manifest = json.loads(store.values[spec.datasets[0].manifest.sha256])
    if case == "extra":
        manifest["objects"].append({**manifest["objects"][0], "name": "unused"})
    elif case == "count":
        manifest["objects"][0]["row_count"] += 1
    elif case == "schema":
        manifest["objects"][0]["schema_version"] = "other-v1"
    elif case == "bytes":
        manifest["objects"][0]["artifact"] = spec.market.table.artifact.model_dump()
    elif case == "expired":
        manifest["rights"]["retention_expires_at"] = AT.isoformat()
    else:
        manifest["retrieved_at"] = "2026-09-12T00:00:00Z"
    spec = changed_manifest(spec, store, **manifest)
    with pytest.raises(ResearchError):
        admit_monthly(spec, store, evaluated_at=AT)
    if case != "count":
        assert store.reads == [spec.datasets[0].manifest.sha256]


def test_manifest_must_be_canonical_even_when_its_raw_hash_matches() -> None:
    """Extra whitespace or duplicate members cannot identify a second canonical dataset version."""
    from factorforge.backtests.admission import admit_monthly

    spec, store = original_strategy()
    wire = spec.model_dump(mode="json")
    original = spec.datasets[0].version_id
    raw = store.values[original] + b" "
    ref = store.put(raw, media_type="application/json")
    wire["datasets"][0].update(version_id=ref.sha256, manifest=ref.model_dump())
    for binding in [
        wire["universe"],
        wire["market"],
        *wire["signal_inputs"],
        wire["evaluation"]["benchmark"],
        wire["evaluation"]["risk_free"],
    ]:
        binding["table"]["dataset_version"] = ref.sha256
    spec = RawStrategySpec.model_validate_json(json.dumps(wire))
    with pytest.raises(ResearchError) as caught:
        admit_monthly(spec, store, evaluated_at=AT)
    assert caught.value.code == "MONTHLY_MANIFEST_IDENTITY"


def test_receipt_and_verified_store_do_not_grant_unlisted_access() -> None:
    """A receipt is checked metadata and a pinned view does not forward arbitrary input reads."""
    from pydantic import ValidationError

    from factorforge.backtests.admission import AdmissionReceipt, admit_monthly

    spec, store = original_strategy()
    admitted = admit_monthly(spec, store, evaluated_at=AT)
    receipt = admitted.receipt
    assert AdmissionReceipt.model_validate_json(receipt.canonical_bytes()) == receipt
    for updates in (
        {"verified_refs": tuple(reversed(receipt.verified_refs))},
        {"verified_refs": receipt.verified_refs * 2},
        {"manifest_version_ids": ("0" * 64,)},
        {"calendar_sha256": "0" * 64},
        {"monthly_ref": reference(b"unknown", "application/json", 100)},
    ):
        with pytest.raises(ValidationError):
            receipt.model_copy(update=updates).canonical_bytes()
    reads = list(store.reads)
    with pytest.raises(ResearchError):
        admitted.store.get(reference(b"unknown", "application/json", 100))
    assert reads == store.reads


def test_forged_strategy_is_revalidated_before_source_reads() -> None:
    """Copied frozen models do not bypass the contract at this public execution boundary."""
    from factorforge.backtests.admission import admit_monthly

    spec, store = original_strategy()
    spec = spec.model_copy(update={"formula": "unbound"})
    with pytest.raises(ResearchError):
        admit_monthly(spec, store, evaluated_at=AT)
    assert store.reads == []


def test_separate_manifest_roles_preserve_exact_version_closure() -> None:
    """A supported dataset split verifies both manifests before reading either one's inputs."""
    from factorforge.backtests.admission import admit_monthly
    from factorforge.domain.datasets import DatasetManifest

    spec, store = original_strategy()
    manifest = json.loads(store.values[spec.datasets[0].manifest.sha256])
    split = []
    for name, names in (("signals-only", {"signals"}), ("market-only", {"market", "intervals"})):
        value = {
            **manifest,
            "name": name,
            "objects": [item for item in manifest["objects"] if item["name"] in names],
        }
        item = DatasetManifest.model_validate_json(json.dumps(value))
        ref = store.put(item.canonical_bytes(), media_type="application/json")
        split.append((names, ref))
    wire = spec.model_dump(mode="json")
    wire["datasets"] = [
        {"version_id": ref.sha256, "manifest": ref.model_dump()} for _, ref in split
    ]
    for binding in [
        wire["universe"],
        wire["market"],
        *wire["signal_inputs"],
        wire["evaluation"]["benchmark"],
        wire["evaluation"]["risk_free"],
    ]:
        binding["table"]["dataset_version"] = next(
            ref.sha256 for names, ref in split if binding["table"]["object_name"] in names
        )
    spec = RawStrategySpec.model_validate_json(json.dumps(wire))
    admitted = admit_monthly(spec, store, evaluated_at=AT)
    assert len(admitted.manifests) == 2
    assert store.reads[:2] == sorted(ref.sha256 for _, ref in split)


def test_wrong_calendar_identity_and_nonbyte_provider_fail() -> None:
    """Canonical JSON and exact named calendar identity remain independent gates."""
    from factorforge.backtests.admission import admit_monthly

    spec, store = original_strategy()
    timing = spec.timing.model_copy(update={"calendar_id": "wrong-calendar"})
    with pytest.raises(ResearchError) as caught:
        admit_monthly(spec.model_copy(update={"timing": timing}), store, evaluated_at=AT)
    assert caught.value.code == "MONTHLY_CALENDAR_IDENTITY"
    store.values[spec.datasets[0].manifest.sha256] = "not bytes"  # type: ignore[assignment]
    with pytest.raises(ResearchError) as caught:
        admit_monthly(spec, store, evaluated_at=AT)
    assert caught.value.code == "MONTHLY_SOURCE_INVALID"


def test_output_identity_and_receipt_utc_are_checked() -> None:
    """Trusted-provider failures and copied non-UTC receipts cannot pass as canonical evidence."""
    from datetime import timedelta, timezone

    from pydantic import ValidationError

    from factorforge.backtests.admission import admit_monthly

    class WrongOutput(MemoryStore):
        """Return a valid but unrelated content reference to probe provider success handling."""

        def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
            """The fixture supplies a wrong identity only during output publication."""
            return reference(b"wrong", media_type, 100)

    spec, source = original_strategy()
    store = WrongOutput()
    store.values = source.values
    admitted = admit_monthly(spec, store, evaluated_at=AT)
    with pytest.raises(ResearchError) as caught:
        admitted.store.put(b"actual")
    assert caught.value.code == "MONTHLY_OUTPUT_IDENTITY"
    with pytest.raises(ValidationError):
        admitted.receipt.model_copy(
            update={"evaluated_at": AT.astimezone(timezone(timedelta(hours=1)))}
        ).canonical_bytes()


def test_provider_cannot_rewrite_expected_reference_during_read() -> None:
    """Even an in-process provider receives a detached copy of the expected content identity."""
    from factorforge.backtests.admission import admit_monthly

    class MutatingStore(MemoryStore):
        """Alter the received reference to claim that substituted evidence was requested."""

        def get(self, ref: ArtifactRef) -> bytes:
            """Target opaque evidence so JSON parsing cannot incidentally detect replacement."""
            if ref.sha256 == target:
                replacement = reference(b"substituted evidence", ref.media_type, 100)
                object.__setattr__(ref, "sha256", replacement.sha256)
                object.__setattr__(ref, "size_bytes", replacement.size_bytes)
                return b"substituted evidence"
            return super().get(ref)

    spec, original = original_strategy()
    before = spec.canonical_bytes()
    target = spec.source_refs[0].sha256
    store = MutatingStore()
    store.values = original.values
    with pytest.raises(ResearchError) as caught:
        admit_monthly(spec, store, evaluated_at=AT)
    assert caught.value.code == "ARTIFACT_INTEGRITY"
    assert spec.canonical_bytes() == before


@pytest.mark.parametrize("error", [KeyError("private locator"), OSError("private path")])
def test_unexpected_provider_errors_have_safe_typed_diagnostics(error: Exception) -> None:
    """Storage adapters cannot leak raw host diagnostics through the local admission API."""
    from factorforge.backtests.admission import admit_monthly

    class FailedStore(MemoryStore):
        """A broken provider has no valid artifact response to interpret."""

        def get(self, ref: ArtifactRef) -> bytes:
            """Raise the authored provider failure before returning any source content."""
            raise error

    spec, _ = original_strategy()
    with pytest.raises(ResearchError) as caught:
        admit_monthly(spec, FailedStore(), evaluated_at=AT)
    assert caught.value.code == "MONTHLY_SOURCE_UNAVAILABLE"
    assert "private" not in str(caught.value)


def test_public_monthly_loader_rejects_nonbyte_provider_result() -> None:
    """A hash-compatible memoryview is not a supported strict JSON input byte response."""
    from factorforge.data.monthly_signals import load_monthly

    spec, store = original_strategy()
    ref = spec.universe.table.artifact
    store.values[ref.sha256] = memoryview(store.values[ref.sha256])  # type: ignore[assignment]
    with pytest.raises(ResearchError) as caught:
        load_monthly(ref, store)
    assert caught.value.code == "MONTHLY_SOURCE_INVALID"


def test_provider_research_error_is_preserved_and_monthly_loader_clones_refs() -> None:
    """Known provider failure codes survive translation; source loaders retain original hashes."""
    from factorforge.backtests.admission import admit_monthly
    from factorforge.data.monthly_signals import load_monthly

    class KnownFailure(MemoryStore):
        """Return the provider's established not-found diagnostic through both public loaders."""

        def get(self, ref: ArtifactRef) -> bytes:
            """No byte interpretation occurs after this canonical provider error."""
            raise ResearchError("ARTIFACT_MISSING", "Unavailable.", 404)

    spec, store = original_strategy()
    ref = spec.universe.table.artifact
    for operation in (
        lambda: admit_monthly(spec, KnownFailure(), evaluated_at=AT),
        lambda: load_monthly(ref, KnownFailure()),
    ):
        with pytest.raises(ResearchError) as caught:
            operation()
        assert caught.value.code == "ARTIFACT_MISSING"
    with pytest.raises(ResearchError) as caught:
        load_monthly(ref.model_copy(update={"size_bytes": -1}), store)
    assert caught.value.code == "MONTHLY_SOURCE_INVALID"
