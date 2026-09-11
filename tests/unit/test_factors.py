"""Complete fictional factor contracts never infer execution choices from nullable extraction."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import pytest
from pydantic import ValidationError

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.datasets import DatasetManifest, DatasetObject, UsageRights
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import FactorSpec
from factorforge.factors.hypotheses import Hypothesis, HypothesisQueue, rank_hypotheses


def specification() -> dict[str, object]:
    """A tiny authored ratio strategy explicitly declares each supported execution convention."""
    artifact = {"sha256": "a" * 64, "size_bytes": 2, "media_type": "application/json"}
    table = {
        "dataset_version": "b" * 64,
        "object_name": "facts",
        "schema_version": "fiction-v1",
        "artifact": artifact,
    }

    def column(name: str, *, unit: str = "USD", frequency: str = "annual") -> dict[str, object]:
        """Every numeric column declares its exact unit and known-at mapping."""
        return {
            "name": name,
            "table": table,
            "value_field": name,
            "unit": unit,
            "frequency": frequency,
            "period_context": "instant",
            "security_id_field": "security_id",
            "available_at_field": "available_at",
            "period_end_field": "period_end",
            "period_start_field": None,
            "revision_field": "revision",
            "revision_policy": "latest_available_then_revision_reject_conflicts",
            "history_observations": 1,
        }

    returns = column("returns", unit="return_decimal", frequency="daily")
    return {
        "factor_id": "fiction-ratio",
        "version": "v1",
        "name": "Fictional income/assets ratio",
        "source_refs": (artifact,),
        "datasets": ({"version_id": "b" * 64, "manifest": {**artifact, "sha256": "b" * 64}},),
        "signal_inputs": (column("income"), column("assets")),
        "formula": "income / assets",
        "signal_unit": "dimensionless",
        "universe": {
            "table": table,
            "security_id_namespace": "fiction-security-id",
            "security_id_field": "security_id",
            "included_field": "included",
            "effective_at_field": "effective_at",
            "available_at_field": "available_at",
            "policy": "known_effective_events",
            "eligibility": "historical_membership_only",
        },
        "timing": {
            "calendar": artifact,
            "calendar_id": "fiction-calendar-v1",
            "timezone": "UTC",
            "formation": "session_close",
            "trade": "subsequent_session_open",
            "trade_delay_sessions": 1,
            "rebalance": "monthly_last_session",
            "lookback_months": None,
            "formation_lag_months": 0,
            "holding_months": 1,
            "vintage_allocation": "nonoverlapping",
            "within_cohort": "buy_and_hold",
        },
        "portfolio": {
            "direction": "long_high_short_low",
            "bucket_count": 2,
            "bucket_allocation": "balanced_contiguous_low_remainder",
            "weighting": "equal_weight",
            "weight_input": None,
            "breakpoints": "all_eligible",
            "ties": "stable_security_id",
            "minimum_bucket_size": 1,
            "long_exposure": 1,
            "short_exposure": 1,
            "sizing_basis": "pre_trade_nav",
            "short_proceeds": "segregated",
            "cash_return": "zero",
        },
        "costs": {
            "commission_bps": 1,
            "slippage_bps": 1,
            "borrow_bps_annual": 0,
            "financing_bps_annual": 0,
            "turnover": "absolute_change_from_drifted_weights",
            "charge": "all_trades",
            "day_count": "actual_365",
        },
        "policies": {
            "missing_signal": "exclude_at_formation",
            "missing_return": "fail",
            "unknown_terminal": "fail",
            "corporate_actions": "total_return_includes_actions_and_delisting",
            "point_in_time": "available_at_lte_formation_lt_trade",
            "winsorization": "none",
            "standardization": "none",
            "neutralization": "none",
        },
        "returns": returns,
        "evaluation": {
            "benchmark": {**returns, "name": "benchmark", "value_field": "benchmark"},
            "risk_free": {**returns, "name": "risk_free", "value_field": "risk_free"},
            "sample_start": date(2020, 1, 1),
            "sample_end": date(2020, 2, 29),
            "sample_end_policy": "liquidate_at_last_session_with_costs",
            "metrics": ("net_mean", "net_sharpe", "hac_tstat", "max_drawdown", "turnover"),
            "annualization": 252,
            "hac_lags": 1,
            "seeds": (0,),
        },
    }


def test_complete_contract_has_distinct_content_and_execution_identities() -> None:
    """Renaming a candidate preserves exact execution deduplication but changes its source
    record."""
    spec = FactorSpec.model_validate(specification())
    renamed = FactorSpec.model_validate(
        specification() | {"factor_id": "another", "name": "Another name"}
    )
    assert spec.sha256 != renamed.sha256
    assert spec.execution_sha256 == renamed.execution_sha256


@pytest.mark.parametrize(
    "formula", ["income + assets", "income / assets", "(income + assets) / assets"]
)
def test_closed_formula_uses_only_declared_inputs(formula: str) -> None:
    """The safe DSL remains authoritative while dimensional output must match the declared
    signal."""
    value = specification() | {
        "formula": formula,
        "signal_unit": "USD" if formula == "income + assets" else "dimensionless",
    }
    assert FactorSpec.model_validate(value).formula == formula


@pytest.mark.parametrize(
    "formula", ["income / unknown", "__import__('os')", "assets.real", "income ** 2", "income + 1"]
)
def test_unsafe_unknown_or_dimensionally_invalid_formula_is_rejected(formula: str) -> None:
    """Executable admission neither invents an input nor performs an implicit unit conversion."""
    with pytest.raises(ValidationError):
        FactorSpec.model_validate(specification() | {"formula": formula})


@pytest.mark.parametrize(
    "field", ["costs", "timing", "policies", "universe", "evaluation", "datasets", "returns"]
)
def test_execution_sections_are_required(field: str) -> None:
    """Missing execution details are draft blockers, not permissive defaults."""
    value = specification()
    value.pop(field)
    with pytest.raises(ValidationError):
        FactorSpec.model_validate(value)


def test_queue_requires_verified_contract_and_keeps_unresolved_hypotheses_blocked() -> None:
    """Readiness must come from verified inputs and explicit choices rather than a model score."""

    with TemporaryDirectory(prefix="factorforge-hypotheses-") as directory:
        store = LocalArtifactStore(Path(directory))
        candidate = Hypothesis(
            hypothesis_id="draft",
            statement="Income/assets predicts later returns.",
            mechanism="A fictional accounting signal may sort future returns.",
            expected_direction="positive",
            source_refs=(store.put(b"Original fictional hypothesis."),),
            factor_spec=None,
            unresolved_questions=("Which historical universe is supported?",),
            novelty=1.0,
            specificity=1.0,
        )
        queue = rank_hypotheses((candidate,), store, at=datetime.now(UTC))
        assert queue.queued_ids == ()
        assert queue.entries[0].status == "blocked"
        assert set(queue.entries[0].blockers) == {"missing_specification", "unresolved_questions"}


def stored_specification(
    store: ArtifactStore, *, manifest_changes: dict[str, object] | None = None, large: bool = False
) -> FactorSpec:
    """Author verifiable fictional bytes; the queue checks declarations, not an accounting
    backtest."""

    rows = [
        {
            "security_id": f"SEC-{name}",
            "income": income,
            "assets": 100,
            "available_at": "2020-01-15T12:00:00Z",
            "period_end": "2019-12-31",
            "revision": 0,
            "included": True,
            "effective_at": "2019-01-01T00:00:00Z",
            "returns": 0.01,
            "benchmark": 0.0,
            "risk_free": 0.0,
        }
        for name, income in zip("ABCD", [5, 10, 15, 20], strict=True)
    ]
    data_ref = store.put(json.dumps(rows).encode(), media_type="application/json")
    if large:
        data_ref = ArtifactRef(
            sha256="c" * 64, size_bytes=70 * 1024 * 1024, media_type="application/json"
        )
    values: dict[str, object] = dict(
        name="fictional-contract",
        kind="original_fixture",
        provider="Authored test",
        source_version="fiction-v1",
        retrieved_at=datetime(2026, 9, 11, tzinfo=UTC),
        coverage_start=date(2019, 1, 1),
        coverage_end=date(2020, 2, 29),
        security_id_namespace="fiction-security-id",
        universe_policy="known-effective-events",
        availability_policy="explicit-authored-timestamps",
        corporate_action_policy="total-return-includes-actions-and-delisting",
        delisting_policy="explicit-total-return-or-fail",
        rights=UsageRights(
            provenance="Original fictional test bytes.", permitted_uses=("local_research",)
        ),
        objects=(
            DatasetObject(
                name="facts", schema_version="fiction-v1", row_count=4, artifact=data_ref
            ),
        ),
    )
    manifest = DatasetManifest.model_validate(values | (manifest_changes or {}))
    manifest_ref = store.put(manifest.canonical_bytes(), media_type="application/json")
    calendar_ref = store.put(
        b'{"calendar_id":"fiction-calendar-v1","sessions":["2020-01-31","2020-02-03","2020-02-28"]}',
        media_type="application/json",
    )
    value = specification()
    cast(dict[str, object], cast(dict[str, object], value["universe"])["table"]).update(
        dataset_version=manifest.version_id, artifact=data_ref.model_dump(mode="python")
    )
    value["datasets"] = ({"version_id": manifest.version_id, "manifest": manifest_ref},)
    value["source_refs"] = (store.put(b"Original fictional ratio hypothesis."),)
    cast(dict[str, object], value["timing"])["calendar"] = calendar_ref
    return FactorSpec.model_validate(value)


def hypothesis(
    spec: FactorSpec, *, name: str = "a", novelty: float = 0.5, specificity: float = 0.5
) -> Hypothesis:
    """Metadata scores are proposed ordering hints; testability is never supplied by a model."""
    return Hypothesis(
        hypothesis_id=name,
        statement="Income/assets may predict returns.",
        mechanism="A fictional accounting relation.",
        expected_direction="positive",
        source_refs=spec.source_refs,
        factor_spec=spec,
        unresolved_questions=(),
        novelty=novelty,
        specificity=specificity,
    )


def queue_for(candidates: tuple[Hypothesis, ...], store: ArtifactStore) -> HypothesisQueue:
    """Use one declared current assessment time so rights checks remain reproducible."""
    return rank_hypotheses(candidates, store, at=datetime(2026, 9, 11, tzinfo=UTC))


def test_complete_fictional_contract_ranks_and_deduplicates_by_execution() -> None:
    """Higher declared priority keeps one execution while duplicate IDs remain observable."""
    with TemporaryDirectory(prefix="factorforge-queue-ready-") as directory:
        store = LocalArtifactStore(Path(directory))
        spec = stored_specification(store)
        first = hypothesis(spec, name="a", novelty=0.5, specificity=0.5)
        second = hypothesis(
            spec.model_copy(update={"factor_id": "renamed"}), name="b", novelty=1.0, specificity=1.0
        )
        queue = queue_for((first, second), store)
        assert queue.queued_ids == ("b",)
        assert queue.entries[0].ranking_score == 1.0
        assert queue.entries[1].status == "duplicate" and queue.entries[1].duplicate_of == "b"
        reordered = queue_for((second, first), store)
        assert reordered == queue


@pytest.mark.parametrize(
    "changes,blocker",
    [
        ({"security_id_namespace": "tickers"}, "security_id_namespace_mismatch"),
        ({"universe_policy": "current-members"}, "unsupported_universe_policy"),
        ({"availability_policy": "period-end-proxy"}, "unsupported_availability_policy"),
        ({"corporate_action_policy": "raw-prices"}, "unsupported_return_or_exit_policy"),
        ({"delisting_policy": "ignore"}, "unsupported_return_or_exit_policy"),
        ({"coverage_start": date(2020, 1, 2)}, "insufficient_dataset_coverage"),
    ],
)
def test_known_data_contract_failures_block_planning(
    changes: dict[str, object], blocker: str
) -> None:
    """A valid manifest can still be incompatible with the requested execution semantics."""
    with TemporaryDirectory(prefix="factorforge-queue-policy-") as directory:
        store = LocalArtifactStore(Path(directory))
        spec = stored_specification(store, manifest_changes=changes)
        queue = queue_for((hypothesis(spec),), store)
        assert queue.queued_ids == () and blocker in queue.entries[0].blockers


@pytest.mark.parametrize("expired", [False, True])
def test_unknown_or_expired_use_rights_block_planning(expired: bool) -> None:
    """Readiness never substitutes for a dataset's declared permitted use and retention term."""
    with TemporaryDirectory(prefix="factorforge-queue-rights-") as directory:
        store = LocalArtifactStore(Path(directory))
        rights = UsageRights(
            provenance="Authored test terms.",
            permitted_uses=("local_research",) if expired else (),
            retention_expires_at=datetime(2026, 9, 10, tzinfo=UTC) if expired else None,
        )
        spec = stored_specification(store, manifest_changes={"rights": rights})
        queue = queue_for((hypothesis(spec),), store)
        assert queue.queued_ids == () and "dataset_use_not_permitted" in queue.entries[0].blockers


@pytest.mark.parametrize("component", ["source", "calendar", "data", "manifest"])
def test_missing_or_corrupt_referenced_bytes_block_planning(component: str) -> None:
    """A complete metadata contract cannot authorize work from absent or tampered local objects."""
    with TemporaryDirectory(prefix="factorforge-queue-corrupt-") as directory:
        root = Path(directory)
        store = LocalArtifactStore(root)
        spec = stored_specification(store)
        refs = {
            "source": spec.source_refs[0],
            "calendar": spec.timing.calendar,
            "data": spec.returns.table.artifact,
            "manifest": spec.datasets[0].manifest,
        }
        ref = refs[component]
        path = root / "sha256" / ref.sha256[:2] / ref.sha256
        path.write_bytes(b"tampered")
        queue = queue_for((hypothesis(spec),), store)
        assert queue.queued_ids == ()
        assert queue.entries[0].blockers == (
            ("manifest_unavailable_or_invalid",)
            if component == "manifest"
            else ("artifact_unavailable_or_corrupt",)
        )


def test_verification_byte_budget_blocks_before_large_object_read() -> None:
    """Manifest declarations cannot admit an unbounded amount of byte verification."""
    with TemporaryDirectory(prefix="factorforge-queue-budget-") as directory:
        store = LocalArtifactStore(Path(directory))
        spec = stored_specification(store, large=True)
        queue = queue_for((hypothesis(spec),), store)
        assert queue.entries[0].blockers == ("artifact_verification_budget_exceeded",)


@pytest.mark.parametrize("case", ["delta", "compound", "unary", "multiply"])
def test_temporal_and_dimensional_formula_variants_have_explicit_requirements(case: str) -> None:
    """Accepted operators use the same safe grammar with declared units and observation history."""
    value = specification()
    inputs = cast(tuple[dict[str, object], ...], value["signal_inputs"])
    if case == "delta":
        inputs[0]["history_observations"] = 2
        value["formula"] = "delta(income) / assets"
    elif case == "compound":
        binding = inputs[0] | {
            "name": "monthly_returns",
            "unit": "return_decimal",
            "frequency": "monthly",
            "history_observations": 3,
        }
        value["signal_inputs"] = (binding,)
        value["formula"] = "compound_return(monthly_returns,3)"
        cast(dict[str, object], value["timing"])["lookback_months"] = 3
    else:
        value["formula"] = "-income / assets" if case == "unary" else "income * 2 / assets"
    assert FactorSpec.model_validate(value).signal_unit == "dimensionless"


@pytest.mark.parametrize(
    "case",
    [
        "duplicate_inputs",
        "duplicate_datasets",
        "foreign_table",
        "wrong_returns",
        "wrong_signal_unit",
        "delta_history",
        "compound_history",
        "weight_missing",
        "weight_unit",
        "overlap",
        "holding_alignment",
        "duration",
        "aliased_time",
        "duplicate_metrics",
        "duplicate_seeds",
        "sample_order",
        "ancient_history",
        "comparison_unit",
        "cost_bool",
        "blank_name",
    ],
)
def test_inconsistent_execution_contracts_cannot_enter_queue(case: str) -> None:
    """Structural contradictions fail before artifacts or scores can grant planning readiness."""
    value = specification()
    inputs = cast(tuple[dict[str, object], ...], value["signal_inputs"])
    timing = cast(dict[str, object], value["timing"])
    portfolio = cast(dict[str, object], value["portfolio"])
    evaluation = cast(dict[str, object], value["evaluation"])
    if case == "duplicate_inputs":
        value["signal_inputs"] = (*inputs, inputs[0])
    elif case == "duplicate_datasets":
        value["datasets"] = cast(tuple[object, ...], value["datasets"]) * 2
    elif case == "foreign_table":
        cast(dict[str, object], inputs[0]["table"])["dataset_version"] = "c" * 64
    elif case == "wrong_returns":
        cast(dict[str, object], value["returns"])["unit"] = "USD"
    elif case == "wrong_signal_unit":
        value["signal_unit"] = "shares"
    elif case == "delta_history":
        value["formula"] = "delta(income) / assets"
    elif case == "compound_history":
        value["signal_inputs"] = (inputs[0],)
        value["formula"] = "compound_return(income,3)"
    elif case == "weight_missing":
        portfolio["weighting"] = "value_weight"
    elif case == "weight_unit":
        portfolio.update(weighting="value_weight", weight_input="income")
        inputs[0]["unit"] = "shares"
    elif case == "overlap":
        timing["holding_months"] = 3
    elif case == "holding_alignment":
        timing.update(
            rebalance="annual_june_last_session",
            holding_months=13,
            vintage_allocation="equal_weight_active",
        )
    elif case == "duration":
        inputs[0]["period_context"] = "duration"
    elif case == "aliased_time":
        inputs[0]["available_at_field"] = "period_end"
    elif case == "duplicate_metrics":
        evaluation["metrics"] = ("net_mean", "net_mean")
    elif case == "duplicate_seeds":
        evaluation["seeds"] = (1, 1)
    elif case == "sample_order":
        evaluation["sample_start"] = date(2021, 1, 1)
    elif case == "ancient_history":
        evaluation["sample_start"] = date(1, 1, 1)
        timing["lookback_months"] = 12
    elif case == "comparison_unit":
        cast(dict[str, object], evaluation["benchmark"])["unit"] = "USD"
    elif case == "cost_bool":
        cast(dict[str, object], value["costs"])["commission_bps"] = True
    else:
        value["name"] = " "
    with pytest.raises(ValidationError):
        FactorSpec.model_validate(value)


@pytest.mark.parametrize(
    "case", ["empty", "duplicate_ids", "forged_score", "blank_question", "naive_time", "too_many"]
)
def test_queue_revalidates_untrusted_inventory_before_reading_artifacts(case: str) -> None:
    """Queue admission cannot be changed by copied models, duplicate identifiers or naive clocks."""
    with TemporaryDirectory(prefix="factorforge-queue-invalid-") as directory:
        store = LocalArtifactStore(Path(directory))
        item = hypothesis(stored_specification(store))
        candidates: tuple[Hypothesis, ...] = (item,)
        at = datetime(2026, 9, 11, tzinfo=UTC)
        if case == "empty":
            candidates = ()
        elif case == "duplicate_ids":
            candidates = (item, item)
        elif case == "forged_score":
            candidates = (item.model_copy(update={"novelty": float("nan")}),)
        elif case == "blank_question":
            candidates = (item.model_copy(update={"unresolved_questions": (" ",)}),)
        elif case == "naive_time":
            at = at.replace(tzinfo=None)
        else:
            candidates = (item,) * 65
        with pytest.raises(ResearchError) as failure:
            rank_hypotheses(candidates, store, at=at)
        assert failure.value.code == "HYPOTHESIS_INVALID"


def test_exact_priority_ties_use_stable_hypothesis_identifier() -> None:
    """Input ordering cannot select a different winner for the same executable contract."""
    with TemporaryDirectory(prefix="factorforge-queue-ties-") as directory:
        store = LocalArtifactStore(Path(directory))
        spec = stored_specification(store)
        queue = queue_for((hypothesis(spec, name="z"), hypothesis(spec, name="a")), store)
        assert queue.queued_ids == ("a",) and queue.entries[1].duplicate_of == "a"


def test_unresolved_complete_specification_is_still_blocked() -> None:
    """A fully filled schema cannot override an explicit unresolved methodological question."""
    with TemporaryDirectory(prefix="factorforge-queue-question-") as directory:
        store = LocalArtifactStore(Path(directory))
        candidate = hypothesis(stored_specification(store)).model_copy(
            update={"unresolved_questions": ("Is the universe complete?",)}
        )
        queue = queue_for((candidate,), store)
        assert queue.queued_ids == () and queue.entries[0].blockers == ("unresolved_questions",)


def test_manifest_table_schema_mismatch_blocks_planning() -> None:
    """Byte identity alone cannot substitute for the declared table interpretation."""
    with TemporaryDirectory(prefix="factorforge-queue-table-") as directory:
        store = LocalArtifactStore(Path(directory))
        spec = stored_specification(store)
        table = spec.returns.table.model_copy(update={"schema_version": "wrong-v1"})
        changed = spec.model_copy(
            update={"returns": spec.returns.model_copy(update={"table": table})}
        )
        queue = queue_for((hypothesis(changed),), store)
        assert queue.queued_ids == () and "table_identity_mismatch" in queue.entries[0].blockers


def test_decimal_literal_fingerprints_preserve_exact_financial_choices() -> None:
    """AST binary-float rounding cannot collapse distinct validated Decimal formulas."""
    first = FactorSpec.model_validate(
        specification() | {"formula": "income/assets + 0.100000000000000000000001"}
    )
    second = FactorSpec.model_validate(
        specification() | {"formula": "income/assets + 0.100000000000000000000002"}
    )
    assert first.execution_sha256 != second.execution_sha256


@pytest.mark.parametrize("identity", ["canonical_bytes", "execution_sha256"])
def test_identity_boundaries_revalidate_forged_contracts(identity: str) -> None:
    """Copied invalid instances must not acquire apparently authoritative content identities."""
    spec = FactorSpec.model_validate(specification()).model_copy(
        update={"formula": "__import__('os')"}
    )
    with pytest.raises(ValidationError):
        if identity == "canonical_bytes":
            spec.canonical_bytes()
        else:
            _ = spec.execution_sha256


@pytest.mark.parametrize("case", ["duration_clock", "revision_value", "universe_clocks"])
def test_timestamp_and_revision_roles_cannot_alias(case: str) -> None:
    """Economic context, publication, revisions and event clocks remain independently identified."""
    value = specification()
    inputs = cast(tuple[dict[str, object], ...], value["signal_inputs"])
    if case == "duration_clock":
        inputs[0].update(period_context="duration", period_start_field="available_at")
    elif case == "revision_value":
        inputs[0]["revision_field"] = "income"
    else:
        cast(dict[str, object], value["universe"])["effective_at_field"] = "available_at"
    with pytest.raises(ValidationError):
        FactorSpec.model_validate(value)


def test_annual_delta_cannot_claim_history_from_an_insufficient_manifest() -> None:
    """Two annual observations require earlier coverage than a current-sample lookback of null."""
    with TemporaryDirectory(prefix="factorforge-queue-history-") as directory:
        store = LocalArtifactStore(Path(directory))
        spec = stored_specification(store)
        values = spec.model_dump()
        values["signal_inputs"] = (
            spec.signal_inputs[0].model_copy(update={"history_observations": 2}),
            spec.signal_inputs[1],
        )
        values["formula"] = "delta(income)/assets"
        changed = FactorSpec.model_validate(values)
        queue = queue_for((hypothesis(changed),), store)
        assert (
            queue.queued_ids == () and "insufficient_dataset_coverage" in queue.entries[0].blockers
        )


def test_verification_budget_admission_precedes_every_artifact_read() -> None:
    """Known oversize declarations cannot consume even manifest reads before budget admission."""

    class ReadProbe(LocalArtifactStore):
        """Track only public verification reads, preserving real content-store behavior."""

        reads = 0

        def get(self, reference: ArtifactRef) -> bytes:
            """Expose whether rejected candidates perform unnecessary artifact retrieval."""
            self.reads += 1
            return super().get(reference)

    with TemporaryDirectory(prefix="factorforge-queue-preread-") as directory:
        store = ReadProbe(Path(directory))
        spec = stored_specification(store, large=True)
        queue = queue_for((hypothesis(spec),), store)
        assert queue.queued_ids == () and store.reads == 0


@pytest.mark.parametrize(
    "case", ["queued_ids", "queued_blockers", "naive_time", "invalid_hash", "unknown_duplicate"]
)
def test_saved_queue_rejects_inconsistent_reloaded_state(case: str) -> None:
    """Serialization cannot make a blocked or mismatched candidate appear admitted."""
    with TemporaryDirectory(prefix="factorforge-queue-reload-") as directory:
        store = LocalArtifactStore(Path(directory))
        queue = queue_for((hypothesis(stored_specification(store)),), store)
        value = queue.model_dump(mode="json")
        if case == "queued_ids":
            value["queued_ids"] = ["foreign"]
        elif case == "queued_blockers":
            value["entries"][0]["blockers"] = ["unresolved_questions"]
        elif case == "naive_time":
            value["evaluated_at"] = "2026-09-11T00:00:00"
        elif case == "invalid_hash":
            value["entries"][0]["hypothesis_sha256"] = "invalid"
        else:
            value["entries"][0].update(status="duplicate", duplicate_of="foreign")
            value["queued_ids"] = []
        with pytest.raises(ValidationError):
            HypothesisQueue.model_validate_json(json.dumps(value))


def test_comparison_dataset_does_not_inherit_unrelated_signal_warmup() -> None:
    """A separate benchmark does not inherit another table's annual signal history."""
    with TemporaryDirectory(prefix="factorforge-queue-roles-") as directory:
        store = LocalArtifactStore(Path(directory))
        spec = stored_specification(store)
        original = DatasetManifest.model_validate_json(store.get(spec.datasets[0].manifest))
        comparison = original.model_copy(
            update={
                "coverage_start": spec.evaluation.sample_start,
                "security_id_namespace": "global-series",
            }
        )
        reference = store.put(comparison.canonical_bytes(), media_type="application/json")
        table = spec.evaluation.benchmark.table.model_copy(
            update={"dataset_version": comparison.version_id}
        )
        value = spec.model_dump()
        value["datasets"] = (
            *spec.datasets,
            {"version_id": comparison.version_id, "manifest": reference},
        )
        value["evaluation"] = spec.evaluation.model_copy(
            update={
                "benchmark": spec.evaluation.benchmark.model_copy(update={"table": table}),
                "risk_free": spec.evaluation.risk_free.model_copy(update={"table": table}),
            }
        )
        changed = FactorSpec.model_validate(value)
        required = changed.required_coverage()
        assert required[comparison.version_id] == spec.evaluation.sample_start
        assert required[spec.datasets[0].version_id] == date(2019, 1, 1)
        assert queue_for((hypothesis(changed),), store).queued_ids == ("a",)


def test_reference_size_conflict_blocks_without_byte_reads() -> None:
    """One hash cannot describe two different lengths even across hypothesis/source roles."""
    with TemporaryDirectory(prefix="factorforge-queue-size-") as directory:
        store = LocalArtifactStore(Path(directory))
        spec = stored_specification(store)
        wrong = spec.source_refs[0].model_copy(
            update={"size_bytes": spec.source_refs[0].size_bytes + 1}
        )
        candidate = hypothesis(spec).model_copy(update={"source_refs": (wrong,)})
        queue = queue_for((candidate,), store)
        assert queue.entries[0].blockers == ("artifact_identity_conflict",)


@pytest.mark.parametrize("case", ["version", "manifest_size", "revision_policy"])
def test_invalid_manifest_links_and_revision_policy_fail_admission(case: str) -> None:
    """Metadata references must close over canonical manifests and actual revision columns."""
    value = specification()
    if case == "revision_policy":
        cast(tuple[dict[str, object], ...], value["signal_inputs"])[0]["revision_field"] = None
    else:
        link = cast(tuple[dict[str, object], ...], value["datasets"])[0]
        if case == "version":
            link["version_id"] = "e" * 64
        else:
            cast(dict[str, object], link["manifest"])["size_bytes"] = 256 * 1024 + 1
    with pytest.raises(ValidationError):
        FactorSpec.model_validate(value)


@pytest.mark.parametrize(
    "case", ["factor_presence", "missing_duplicate", "missing_factor", "duplicate_ids"]
)
def test_saved_queue_rejects_additional_status_contradictions(case: str) -> None:
    """Reloaded records retain factor identities and unique inventory requirements."""
    with TemporaryDirectory(prefix="factorforge-queue-consistency-") as directory:
        store = LocalArtifactStore(Path(directory))
        value = queue_for((hypothesis(stored_specification(store)),), store).model_dump(mode="json")
        entry = value["entries"][0]
        if case == "factor_presence":
            entry["factor_sha256"] = None
        elif case == "missing_duplicate":
            entry["status"] = "duplicate"
        elif case == "missing_factor":
            entry.update(factor_sha256=None, execution_sha256=None)
        else:
            value["entries"].append(dict(entry))
            value["queued_ids"].append(entry["hypothesis_id"])
        with pytest.raises(ValidationError):
            HypothesisQueue.model_validate_json(json.dumps(value))


@pytest.mark.parametrize("case", ["annual_duration", "daily", "daily_underflow", "per_share"])
def test_history_context_and_unit_variants_remain_explicit(case: str) -> None:
    """History metadata follows input roles while dimensional arithmetic retains exact units."""
    value = specification()
    inputs = cast(tuple[dict[str, object], ...], value["signal_inputs"])
    if case == "annual_duration":
        inputs[0].update(period_context="duration", period_start_field="period_start")
        spec = FactorSpec.model_validate(value)
        assert spec.required_coverage()[spec.datasets[0].version_id] == date(2018, 1, 1)
    elif case == "per_share":
        inputs[1]["unit"] = "shares"
        value["signal_unit"] = "USD_per_share"
        assert FactorSpec.model_validate(value).signal_unit == "USD_per_share"
    else:
        for binding in inputs:
            binding["frequency"] = "daily"
        if case == "daily_underflow":
            cast(dict[str, object], value["evaluation"])["sample_start"] = date(1, 1, 1)
            with pytest.raises(ValidationError):
                FactorSpec.model_validate(value)
        else:
            spec = FactorSpec.model_validate(value)
            assert spec.required_coverage()[spec.datasets[0].version_id] == date(2019, 12, 31)


def test_cross_currency_or_quantity_addition_never_converts_units() -> None:
    """Both declared operands must have matching dimensions before addition is admitted."""
    value = specification() | {"formula": "income + assets", "signal_unit": "USD"}
    cast(tuple[dict[str, object], ...], value["signal_inputs"])[1]["unit"] = "shares"
    with pytest.raises(ValidationError, match="equal units"):
        FactorSpec.model_validate(value)


def test_manifest_canonical_identity_must_match_exact_stored_bytes() -> None:
    """A self-consistent pointer to reformatted metadata is not the catalog's canonical version."""
    with TemporaryDirectory(prefix="factorforge-queue-manifest-") as directory:
        store = LocalArtifactStore(Path(directory))
        spec = stored_specification(store)
        original = json.loads(store.get(spec.datasets[0].manifest))
        rewritten = store.put(
            json.dumps(original, indent=2).encode(), media_type="application/json"
        )
        value = json.loads(
            json.dumps(spec.model_dump(mode="json")).replace(
                spec.datasets[0].version_id, rewritten.sha256
            )
        )
        value["datasets"][0]["manifest"] = rewritten.model_dump(mode="json")
        changed = FactorSpec.model_validate_json(json.dumps(value))
        queue = queue_for((hypothesis(changed),), store)
        assert queue.queued_ids == () and queue.entries[0].blockers == (
            "manifest_identity_mismatch",
        )


def test_saved_queue_cannot_promote_exact_duplicate_into_admitted_inventory() -> None:
    """Consistent-looking status edits cannot bypass execution identity deduplication."""
    with TemporaryDirectory(prefix="factorforge-queue-dedup-") as directory:
        store = LocalArtifactStore(Path(directory))
        candidate = hypothesis(stored_specification(store))
        other = candidate.model_copy(update={"hypothesis_id": "b"})
        value = queue_for((candidate, other), store).model_dump(mode="json")
        assert value["entries"][1]["status"] == "duplicate"
        value["entries"][1].update(status="queued", duplicate_of=None)
        value["queued_ids"] = ["a", "b"]
        with pytest.raises(ValidationError, match="execution identities must be unique"):
            HypothesisQueue.model_validate_json(json.dumps(value))


@pytest.mark.parametrize("field", ["bucket_allocation", "sizing_basis"])
def test_portfolio_partition_and_sizing_choices_are_explicit(field: str) -> None:
    """An older draft cannot inherit newly specified economic choices through defaults."""
    value = specification()
    portfolio = cast(dict[str, object], value["portfolio"])
    portfolio.pop(field, None)
    with pytest.raises(ValidationError):
        FactorSpec.model_validate(value)


def test_previous_factor_schema_is_not_silently_reinterpreted() -> None:
    """Migrating version one requires explicit partition and sizing choices."""
    with pytest.raises(ValidationError):
        FactorSpec.model_validate(specification() | {"schema_version": "factor-spec-v1"})
