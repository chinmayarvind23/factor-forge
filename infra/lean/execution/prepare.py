"""Translate admitted scalar arithmetic source inputs into a separate LEAN execution trial."""

import ast
import hashlib
import io
import json
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from factorforge.backtests.admission import admit_monthly
from factorforge.data.artifacts import ArtifactStore, verify_bytes
from factorforge.data.validation_fixture import prepare_validation_fixture
from factorforge.domain.calendar import plan_formations
from factorforge.domain.formula import parse_formula
from factorforge.domain.raw_strategy import RawStrategySpec
from infra.lean.spike.prepare import build_files as seeded_files


def arithmetic_tree(expression: str) -> dict[str, object]:
    """Translate syntax only; LEAN evaluates raw inputs with its own rational interpreter."""

    def convert(node: ast.AST) -> dict[str, object]:
        """A closed operator vocabulary excludes calls, runtime code and derived scores."""
        if isinstance(node, ast.Name):
            return {"kind": "input", "name": node.id}
        if isinstance(node, ast.Constant):
            value = Fraction(ast.get_source_segment(expression, node) or "")
            return {
                "kind": "number",
                "numerator": str(value.numerator),
                "denominator": str(value.denominator),
            }
        if isinstance(node, ast.UnaryOp):
            return {
                "kind": "negative" if isinstance(node.op, ast.USub) else "positive",
                "value": convert(node.operand),
            }
        if isinstance(node, ast.BinOp):
            names = {ast.Add: "add", ast.Sub: "subtract", ast.Mult: "multiply", ast.Div: "divide"}
            return {
                "kind": names[type(node.op)],
                "left": convert(node.left),
                "right": convert(node.right),
            }
        raise ValueError("LEAN arithmetic profile does not support time-series calls")

    expression = expression.strip()
    return convert(parse_formula(expression).body)


def build_files(repository: Path, artifacts: ArtifactStore) -> dict[str, bytes]:
    """Keep the original example as a wrapper around the source-driven scalar translator."""
    spec = prepare_validation_fixture(repository, artifacts)
    return build_strategy_files(
        repository,
        artifacts,
        spec,
        initial_cash=Decimal("1002"),
        evaluated_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
    )


def build_strategy_files(
    repository: Path,
    artifacts: ArtifactStore,
    spec: RawStrategySpec,
    *,
    initial_cash: Decimal,
    evaluated_at: datetime,
) -> dict[str, bytes]:
    """Translate admitted two-ID scalar source data, never Python holdings or performance.

    The current LEAN profile supports one formation and integer-share funding. Reject
    time-series formulas or policies here rather than silently translating a different strategy.
    """
    admission = admit_monthly(spec, artifacts, evaluated_at=evaluated_at)
    spec = admission.spec
    plans = plan_formations(
        admission.calendar,
        spec.timing,
        start=spec.evaluation.sample_start,
        end=spec.evaluation.sample_end,
    )
    if (
        any(binding.history_observations != 1 for binding in spec.signal_inputs)
        or spec.policies.dataset_kind != "original_fixture"
        or spec.timing.formation_lag_months != 0
        or len(plans) != 1
        or spec.portfolio.allocation.bucket_count != 2
        or spec.portfolio.allocation.minimum_bucket_size != 1
        or spec.costs.annual_borrow_bps != 0
        or spec.costs.annual_financing_bps != 0
        or spec.costs.annual_interest_bps != 0
        or plans[0].formation_at.date() != spec.evaluation.sample_start
        or not initial_cash.is_finite()
        or initial_cash <= 0
    ):
        raise ValueError("Unsupported LEAN scalar strategy")
    artifacts = admission.store
    inputs = {}
    for name, ref in (
        ("market", spec.market.table.artifact),
        ("signals", spec.universe.table.artifact),
    ):
        raw = artifacts.get(ref)
        verify_bytes(raw, ref)
        inputs[name] = json.loads(raw)
    if {row["security_id"] for row in inputs["market"]["quotes"]} != {"A", "B"}:
        raise ValueError("LEAN scalar profile requires the original A/B security namespace")
    sessions = [
        row
        for row in admission.calendar.sessions
        if spec.evaluation.sample_start <= row.session_date <= spec.evaluation.sample_end
    ]
    if any(row.session_date.weekday() >= 5 for row in sessions):
        raise ValueError("LEAN scalar profile supports weekday UTC sessions")
    base = seeded_files((repository / "infra/lean/spike/source.json").read_bytes())
    files = {
        name: base[name]
        for name in (
            "data/market-hours/market-hours-database.json",
            "data/symbol-properties/symbol-properties-database.csv",
        )
    }
    source = dict(
        schema_version="original-lean-execution-v4",
        expression=arithmetic_tree(spec.formula),
        initial_cash_usd=str(initial_cash),
        calendar=admission.calendar.model_dump(mode="json"),
        strategy=spec.model_dump(mode="json"),
        **inputs,
    )
    files["source.json"] = json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
    for security, ticker in (("A", "ffa"), ("B", "ffb")):
        files[f"data/equity/usa/map_files/{ticker}.csv"] = (
            f"19980101,{ticker}\n20501231,{ticker}\n".encode()
        )
        files[f"data/equity/usa/factor_files/{ticker}.csv"] = b"19980101,1,1,0\n20501231,1,1,0\n"
        days: dict[str, list[str]] = {}
        for row in inputs["market"]["quotes"]:
            if row["security_id"] != security:
                continue
            at = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
            milliseconds = (at.hour * 3600 + at.minute * 60 + at.second) * 1000
            scaled = Decimal(row["price_usd"]) * 10000
            days.setdefault(at.strftime("%Y%m%d"), []).append(f"{milliseconds},{scaled},1,,0,0\n")
        for day, rows in sorted(days.items()):
            output = io.BytesIO()
            with ZipFile(output, "w", compression=ZIP_STORED) as archive:
                entry = ZipInfo(f"{day}_{ticker}_Trade_Tick.csv", (2024, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100444 << 16
                archive.writestr(entry, "".join(rows).encode())
            files[f"data/equity/usa/tick/{ticker}/{day}_trade.zip"] = output.getvalue()
    config = json.loads(base["config.json"])
    config.update(
        {
            "algorithm-type-name": "FactorForge.LeanExecution.ExecutedEquityAlgorithm",
            "result-handler": "FactorForge.LeanExecution.OriginalFixtureResultHandler",
            "symbol-tick-limit": 2,
        }
    )
    files["config.json"] = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    files["input-manifest.json"] = json.dumps(
        dict(
            schema_version="original-lean-execution-files-v1",
            files=[
                dict(path=name, sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
                for name, raw in sorted(files.items())
            ],
        ),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return files
