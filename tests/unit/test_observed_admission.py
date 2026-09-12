"""Controlled metadata cases test observed admission; they are not empirical market evidence."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_monthly_admission import AT, MemoryStore, original_strategy
from test_monthly_backtest import execute, replace_source

from factorforge.backtests.admission import admit_monthly
from factorforge.domain.datasets import ObservedDatasetManifest, dataset_references
from factorforge.domain.errors import ResearchError
from factorforge.domain.raw_strategy import RawStrategySpec


def declared_observed(
    *, permission: str = "observed_source_short_loan"
) -> tuple[RawStrategySpec, MemoryStore]:
    """Exercise the trusted declaration boundary using explicitly controlled test-only evidence."""
    spec, store = original_strategy()

    def declare_grants(value: dict[str, Any]) -> None:
        """Test declarations remain controlled assertions, not verified lender permissions."""
        for row in value["borrow_grants"]:
            row["permission"] = permission

    spec = replace_source(spec, store, "market", declare_grants)
    manifest = json.loads(store.get(spec.datasets[0].manifest))
    raw = store.put(b"controlled source response", media_type="text/plain")
    code = store.put(b"# controlled normalizer", media_type="text/x-python")
    parameters = store.put(b'{"scope":"controlled test"}', media_type="application/json")
    timing = store.put(b"controlled timing review", media_type="text/plain")
    manifest.update(
        kind="observed",
        availability_policy="explicit-source-availability",
        observed_schema="observed-provenance-v1",
        derivations=[
            dict(
                object_name=obj["name"],
                raw_sources=[raw.model_dump()],
                normalizer=code.model_dump(),
                parameters=parameters.model_dump(),
                timing_evidence=timing.model_dump(),
            )
            for obj in manifest["objects"]
        ],
    )
    parsed = ObservedDatasetManifest.model_validate_json(json.dumps(manifest))
    ref = store.put(parsed.canonical_bytes(), media_type="application/json")
    wire = spec.model_dump(mode="json")
    wire["datasets"] = [dict(version_id=ref.sha256, manifest=ref.model_dump())]
    wire["policies"].update(dataset_kind="observed", short_loan="require_valid_finite_source_grant")
    for binding in [
        wire["universe"],
        wire["market"],
        *wire["signal_inputs"],
        wire["evaluation"]["benchmark"],
        wire["evaluation"]["risk_free"],
    ]:
        binding["table"]["dataset_version"] = ref.sha256
    return RawStrategySpec.model_validate_json(json.dumps(wire)), store


def rewrite_manifest(spec: RawStrategySpec, store: MemoryStore, change: Any) -> RawStrategySpec:
    """Rebind mutations canonically so admission validates the changed metadata."""
    wire = json.loads(store.get(spec.datasets[0].manifest))
    change(wire)
    raw = json.dumps(wire, sort_keys=True, separators=(",", ":")).encode()
    ref = store.put(raw, media_type="application/json")
    value = spec.model_dump(mode="json")
    value["datasets"] = [dict(version_id=ref.sha256, manifest=ref.model_dump())]
    for binding in [
        value["universe"],
        value["market"],
        *value["signal_inputs"],
        value["evaluation"]["benchmark"],
        value["evaluation"]["risk_free"],
    ]:
        binding["table"]["dataset_version"] = ref.sha256
    return RawStrategySpec.model_validate_json(json.dumps(value))


def test_observed_evidence_is_pinned_and_execution_scope_is_preserved() -> None:
    """All raw/transform/timing evidence joins the immutable receipt and can replay offline."""
    spec, store = declared_observed()
    admitted = admit_monthly(spec, store, evaluated_at=AT)
    assert admitted.receipt.scope == "observed-source-admission"
    assert len(admitted.receipt.verified_refs) == len(spec.unique_artifacts()) + 4
    assert all(admitted.store.get(ref) == store.get(ref) for ref in admitted.receipt.verified_refs)
    result = execute(spec, store)
    assert result.status == "completed", result.failure_code
    assert result.scope == "observed-monthly-raw-price-simulator"
    assert execute(spec, store) == result
    with pytest.raises(ValidationError):
        type(result).model_validate(
            result.model_copy(update={"scope": "original-monthly-raw-price-simulator"})
        )


def test_identity_normalization_can_share_source_bytes() -> None:
    """A provider already using the normalized format need not duplicate identical content."""
    spec, store = declared_observed()

    def change(value: dict[str, Any]) -> None:
        """Keep a declared transform while identifying its unchanged raw input."""
        objects = {row["name"]: row["artifact"] for row in value["objects"]}
        for row in value["derivations"]:
            row["raw_sources"] = [objects[row["object_name"]]]

    spec = rewrite_manifest(spec, store, change)
    assert admit_monthly(spec, store, evaluated_at=AT).receipt.scope == "observed-source-admission"


def test_observed_short_cannot_use_original_fixture_permission() -> None:
    """A source provenance declaration cannot promote a synthetic loan into observed borrowing."""
    spec, store = declared_observed(permission="original_fixture_short_loan")
    result = execute(spec, store)
    assert result.status == "failed"
    assert result.failure_code == "MONTHLY_BORROW_PROVENANCE"
    assert result.fills == ()


def test_original_short_cannot_use_observed_source_permission() -> None:
    """Original fixtures must retain their own explicit loan provenance on execution."""
    spec, store = original_strategy()

    def observed_grants(value: dict[str, Any]) -> None:
        """Change only the grant declarations while preserving the original dataset policy."""
        for row in value["borrow_grants"]:
            row["permission"] = "observed_source_short_loan"

    spec = replace_source(spec, store, "market", observed_grants)
    result = execute(spec, store)
    assert result.status == "failed"
    assert result.failure_code == "MONTHLY_BORROW_PROVENANCE"
    assert result.fills == ()


@pytest.mark.parametrize("case", ["missing", "rights", "budget", "aggregate", "conflict", "role"])
def test_invalid_observed_metadata_precedes_economic_reads(case: str) -> None:
    """Source proof cannot be omitted, substituted, enlarged or used without research rights."""
    spec, store = declared_observed()

    def change(value: dict[str, Any]) -> None:
        """Each mutation targets one independently enforced admission boundary."""
        if case == "missing":
            value.pop("derivations")
        elif case == "rights":
            value["rights"]["permitted_uses"] = []
        elif case == "budget":
            value["derivations"][0]["raw_sources"][0]["size_bytes"] = 65 * 1024 * 1024
        elif case == "aggregate":
            value["derivations"][0]["raw_sources"] = [
                dict(sha256=char * 64, size_bytes=33 * 1024 * 1024, media_type="text/plain")
                for char in ("a", "b")
            ]
        elif case == "conflict":
            value["derivations"][0]["raw_sources"][0]["media_type"] = "application/json"
        else:
            value["derivations"][0]["object_name"] = "undeclared"

    spec = rewrite_manifest(spec, store, change)
    store.reads.clear()
    with pytest.raises(ResearchError):
        admit_monthly(spec, store, evaluated_at=AT)
    assert spec.market.table.artifact.sha256 not in store.reads


def test_catalog_reference_count_is_bounded_before_io() -> None:
    """Individually valid derivations cannot expand a catalog publication beyond 128 objects."""
    spec, store = declared_observed()
    wire = json.loads(store.get(spec.datasets[0].manifest))
    obj, derivation = wire["objects"][0], wire["derivations"][0]
    wire["objects"], wire["derivations"] = [], []
    for index in range(8):
        name = f"table{index}"
        wire["objects"].append({**obj, "name": name})
        wire["derivations"].append(
            {
                **derivation,
                "object_name": name,
                "raw_sources": [
                    dict(
                        sha256=f"{index * 16 + item + 1:064x}",
                        size_bytes=1,
                        media_type="text/plain",
                    )
                    for item in range(16)
                ],
            }
        )
    manifest = ObservedDatasetManifest.model_validate_json(json.dumps(wire))
    with pytest.raises(ValueError, match="inventory budget"):
        dataset_references(manifest)


def test_corrupt_raw_source_is_rejected() -> None:
    """A correct normalized table cannot hide a missing or modified archived provider response."""
    spec, store = declared_observed()
    manifest = ObservedDatasetManifest.model_validate_json(store.get(spec.datasets[0].manifest))
    store.values[manifest.derivations[0].raw_sources[0].sha256] = b"changed"
    with pytest.raises(ResearchError):
        admit_monthly(spec, store, evaluated_at=AT)


def test_observed_sources_do_not_enter_the_original_lean_profile() -> None:
    """Enabling local source admission cannot silently broaden independent-engine evidence."""
    from infra.lean.execution.prepare import build_strategy_files

    spec, store = declared_observed()
    with pytest.raises(ValueError, match="Unsupported LEAN scalar strategy"):
        build_strategy_files(
            Path(__file__).resolve().parents[2],
            store,
            spec,
            initial_cash=Decimal("1002"),
            evaluated_at=AT,
        )
