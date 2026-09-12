"""Frozen retrospective signal experiments on archived adjusted prices, separate from raw fills."""

import argparse
import hashlib
import json
import math
import statistics
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from time import monotonic
from typing import Any

import polars as pl
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from factorforge.validation.hac import HACRequest, hac_mean
from factorforge.validation.splits import LabelPeriod, purged_fold, walk_forward

SIGNALS = (
    "momentum_3_skip1",
    "momentum_6_skip1",
    "momentum_9_skip1",
    "momentum_12_skip1",
    "reversal_1",
    "reversal_3",
    "low_volatility_3",
    "low_volatility_6",
    "low_volatility_12",
    "low_downside_6",
    "low_downside_12",
    "trend_3",
    "trend_6",
    "trend_12",
    "low_max_daily_1",
)
COSTS = (0, 10, 25)


@contextmanager
def _retain_failure(
    summaries: list[dict[str, Any]], signal: str, cost: int, output: Path
) -> Iterator[None]:
    """Retain every failed experiment without changing the frozen case denominator."""
    try:
        yield
    except Exception as error:
        failed = dict(
            signal=signal,
            cost_bps=cost,
            status="failed",
            n=0,
            total_return=None,
            annualized_sharpe=None,
            max_drawdown=None,
            hac_t=None,
            folds=0,
            error_type=type(error).__name__,
        )
        summaries.append(failed)
        (output / f"{signal}-{cost}.json").write_text(json.dumps(failed), encoding="utf-8")


def annualized_sharpe(values: list[float]) -> float | None:
    """A constant return series has no estimable Sharpe rather than an infinite score."""
    deviation = statistics.stdev(values)
    return math.sqrt(12) * statistics.mean(values) / deviation if deviation > 0 else None


class JsonSpans(SpanExporter):
    """Retain actual local SDK spans without hosted credentials or inferred model calls."""

    def __init__(self, path: Path) -> None:
        """Exclusive output prevents a second study from silently replacing its trace."""
        self.stream = path.open("x", encoding="utf-8")
        self.count = 0

    def export(self, spans: Any) -> SpanExportResult:
        """Write SDK IDs, real timing and attributes for each completed execution span."""
        for span in spans:
            self.stream.write(span.to_json(indent=None) + "\n")
            self.count += 1
        self.stream.flush()
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """Flush retained traces when the local study finishes or raises."""
        self.stream.close()


def load_panel(paths: dict[str, Path]) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    """Validate full aligned source histories before deriving any scores or observing outcomes."""
    if not 4 <= len(paths) <= 50:
        raise ValueError("Supply 4-50 explicitly selected stocks")
    rows, refs = [], []
    expected = None
    for symbol, path in sorted(paths.items()):
        raw = path.read_bytes()
        if not 0 < len(raw) <= 4 * 1024 * 1024:
            raise ValueError("Source exceeds bounded chart response")
        doc = json.loads(raw)
        if doc["chart"]["error"] is not None or len(doc["chart"]["result"]) != 1:
            raise ValueError("Source chart failed")
        source = doc["chart"]["result"][0]
        if source["meta"]["symbol"] != symbol or source["meta"]["currency"] != "USD":
            raise ValueError("Source identity or currency differs")
        times = source["timestamp"]
        prices = source["indicators"]["adjclose"][0]["adjclose"]
        if not 400 <= len(times) <= 10000 or len(prices) != len(times):
            raise ValueError("Source length differs")
        if any(type(t) is not int for t in times) or any(a >= b for a, b in pairwise(times)):
            raise ValueError("Dates must be strictly ordered")
        if expected is not None and times != expected:
            raise ValueError("Source calendars differ; no observations may be dropped")
        expected = times
        for stamp, value in zip(times, prices, strict=True):
            if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
                raise ValueError("Adjusted close must be finite and positive")
            day = datetime.fromtimestamp(stamp, UTC).date()
            rows.append(
                dict(symbol=symbol, date=day, month=day.strftime("%Y-%m"), price=float(value))
            )
        refs.append(
            dict(symbol=symbol, sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        )
    panel = pl.DataFrame(rows).sort(["symbol", "date"])
    if panel.select(pl.struct("symbol", "date").n_unique()).item() != panel.height:
        raise ValueError("Source dates repeat")
    return panel, refs


def signal_score(name: str, closes: list[float], daily_max: list[float], at: int) -> float:
    """Use data through formation only, with explicit skipped months and stable directions."""
    if name == "low_max_daily_1":
        return -daily_max[at]
    length = int(next(part for part in name.split("_") if part.isdigit()))
    if name.startswith("momentum"):
        return closes[at - 1] / closes[at - length] - 1
    if name.startswith("reversal"):
        return -(closes[at] / closes[at - length] - 1)
    if name.startswith("trend"):
        return closes[at] / statistics.mean(closes[at - length + 1 : at + 1]) - 1
    returns = [closes[i] / closes[i - 1] - 1 for i in range(at - length + 1, at + 1)]
    if name.startswith("low_volatility"):
        return -statistics.stdev(returns)
    if name.startswith("low_downside"):
        return -math.sqrt(statistics.mean(min(r, 0) ** 2 for r in returns))
    raise ValueError("Unknown frozen signal")


def period_return(
    weights: dict[str, float],
    old: dict[str, float],
    returns: dict[str, float],
    cost_bps: int,
    *,
    terminal: bool,
) -> tuple[float, dict[str, float], float]:
    """Fund turnover fees from cash and retain drifted weights for the following rebalance.

    Target dollar positions use pre-trade NAV. This is a mathematical long-short return
    portfolio, not broker fills or a margin/borrow simulation. Float64 arithmetic is explicit.
    """
    rate = cost_bps / 10000
    turnover = sum(abs(weights.get(s, 0) - old.get(s, 0)) for s in weights.keys() | old.keys())
    fee = rate * turnover
    ending = {s: weight * (1 + returns[s]) for s, weight in weights.items()}
    if terminal:
        fee += rate * sum(abs(value) for value in ending.values())
    net = sum(weights[s] * returns[s] for s in weights) - fee
    if not math.isfinite(net) or net <= -1:
        raise ValueError("Research portfolio became insolvent")
    return net, {s: value / (1 + net) for s, value in ending.items()}, fee


def run_study(paths: dict[str, Path], output: Path) -> dict[str, Any]:
    """Run all predeclared signal/cost pairs and retain period returns, scores, folds and traces."""
    output.mkdir(parents=True, exist_ok=False)
    started = monotonic()
    panel, sources = load_panel(paths)
    expected_sources = {row["symbol"]: row["sha256"] for row in sources}
    for symbol, path in paths.items():
        raw_source = path.read_bytes()
        if hashlib.sha256(raw_source).hexdigest() != expected_sources[symbol]:
            raise ValueError("Source changed between parsing and archival")
        (output / f"source-{symbol}.json").write_bytes(raw_source)
    panel.write_parquet(output / "source-panel.parquet")
    code = Path(__file__).read_bytes()
    (output / "historical_study.py").write_bytes(code)
    dependency_code = {}
    package = Path(__file__).resolve().parents[1]
    for name in (
        "validation/hac.py",
        "validation/splits.py",
        "domain/accounting.py",
        "domain/performance.py",
        "domain/factors.py",
    ):
        raw_code = (package / name).read_bytes()
        dependency_code[name] = hashlib.sha256(raw_code).hexdigest()
        (output / ("code-" + name.replace("/", "-"))).write_bytes(raw_code)
    freeze = dict(
        schema_version="historical-study-v1",
        sources=sources,
        signals=SIGNALS,
        costs_bps=COSTS,
        code_sha256=hashlib.sha256(code).hexdigest(),
        dependency_code=dependency_code,
        universe=dict(scope="fixed retrospective survivor selection", symbols=sorted(paths)),
        execution="first-session close next month to first-session close the following month",
        portfolio="top two +1, bottom two -1; pre-trade NAV weights; zero borrow/financing",
        scope=(
            "Exploratory historical experiments; not published-factor reproduction "
            "or autonomous LLM research"
        ),
    )
    frozen = json.dumps(freeze, sort_keys=True).encode()
    (output / "freeze.json").write_bytes(frozen)
    months = sorted(panel["month"].unique().to_list())
    if len(months) < 85:
        raise ValueError("Study needs at least 85 complete source months")
    month_numbers = [int(m[:4]) * 12 + int(m[5:]) for m in months]
    if any(b != a + 1 for a, b in pairwise(month_numbers)):
        raise ValueError("Source months are not consecutive")
    histories = {}
    for symbol in sorted(paths):
        data = panel.filter(pl.col("symbol") == symbol).with_columns(
            pl.col("price").pct_change().alias("daily_return")
        )
        grouped = data.group_by("month", maintain_order=True).agg(
            pl.col("price").first().alias("first"),
            pl.col("price").last().alias("last"),
            pl.col("date").first().alias("first_date"),
            pl.col("daily_return").max().fill_null(0).alias("max_daily"),
        )
        histories[symbol] = grouped.to_dict(as_series=False)
    provider = TracerProvider()
    exporter = JsonSpans(output / "spans.jsonl")
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("factorforge.historical-study")
    summaries: list[dict[str, Any]] = []
    try:
        with tracer.start_as_current_span("historical-study"):
            for signal in SIGNALS:
                for cost in COSTS:
                    with (
                        _retain_failure(summaries, signal, cost, output),
                        tracer.start_as_current_span(
                            "historical-experiment", attributes={"signal": signal, "cost_bps": cost}
                        ),
                    ):
                        old: dict[str, float] = {}
                        nav, peak, drawdown = 1.0, 1.0, 0.0
                        periods = []
                        for at in range(12, len(months) - 2):
                            with tracer.start_as_current_span(
                                "monthly-rebalance", attributes={"formation_month": months[at]}
                            ):
                                scores = {
                                    s: signal_score(signal, h["last"], h["max_daily"], at)
                                    for s, h in histories.items()
                                }
                                ranked = sorted(scores, key=lambda s: (scores[s], s))
                                weights = {
                                    s: (
                                        0.5
                                        if s in ranked[-2:]
                                        else -0.5
                                        if s in ranked[:2]
                                        else 0.0
                                    )
                                    for s in ranked
                                }
                                future = {
                                    s: h["first"][at + 2] / h["first"][at + 1] - 1
                                    for s, h in histories.items()
                                }
                                net, old, fee = period_return(
                                    weights, old, future, cost, terminal=at == len(months) - 3
                                )
                                nav *= 1 + net
                                peak = max(peak, nav)
                                drawdown = min(drawdown, nav / peak - 1)
                                first = next(iter(histories.values()))
                                periods.append(
                                    dict(
                                        formation=months[at],
                                        entry=first["first_date"][at + 1].isoformat(),
                                        exit=first["first_date"][at + 2].isoformat(),
                                        scores=scores,
                                        weights=weights,
                                        net_return=net,
                                        fee_fraction=fee,
                                        nav=nav,
                                    )
                                )
                        values = [p["net_return"] for p in periods]
                        hac = hac_mean(
                            HACRequest(
                                values=tuple(Decimal(str(v)) for v in values),
                                lags=3,
                                correction="none",
                            )
                        )
                        labels = tuple(
                            LabelPeriod(
                                start=datetime.fromisoformat(p["entry"]).replace(tzinfo=UTC),
                                end=datetime.fromisoformat(p["exit"]).replace(tzinfo=UTC),
                                available_at=datetime.fromisoformat(p["exit"]).replace(tzinfo=UTC),
                            )
                            for p in periods
                        )
                        folds = walk_forward(labels, initial_train_size=60, test_size=12)
                        diagnostics = [
                            dict(
                                walk_forward=fold.model_dump(mode="json"),
                                purged=purged_fold(
                                    labels,
                                    test_start=fold.test[0],
                                    test_stop=fold.test[-1] + 1,
                                    embargo_seconds=31 * 86400,
                                ).model_dump(mode="json"),
                                test_mean=statistics.mean(values[i] for i in fold.test),
                            )
                            for fold in folds
                        ]
                        summary = dict(
                            signal=signal,
                            cost_bps=cost,
                            status="completed",
                            n=len(values),
                            total_return=nav - 1,
                            annualized_sharpe=annualized_sharpe(values),
                            sharpe_reason="ZERO_VARIANCE"
                            if statistics.stdev(values) == 0
                            else None,
                            max_drawdown=drawdown,
                            hac_t=float(hac.t_statistic.value)
                            if hac.t_statistic.value is not None
                            else None,
                            folds=len(folds),
                        )
                        (output / f"{signal}-{cost}.json").write_text(
                            json.dumps(
                                dict(
                                    summary=summary,
                                    periods=periods,
                                    diagnostics=diagnostics,
                                    hac=hac.model_dump(mode="json"),
                                ),
                                sort_keys=True,
                            ),
                            encoding="utf-8",
                        )
                        summaries.append(summary)
    finally:
        provider.shutdown()
    report = dict(
        scope=freeze["scope"],
        source_rows=panel.height,
        source_count=len(paths),
        start_date=str(panel["date"].min()),
        end_date=str(panel["date"].max()),
        experiments=summaries,
        completed=sum(row["status"] == "completed" for row in summaries),
        total=len(SIGNALS) * len(COSTS),
        span_count=exporter.count,
        runtime_seconds=monotonic() - started,
        dataset_sha256=hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
        freeze_sha256=hashlib.sha256(frozen).hexdigest(),
        metric_note=(
            "Sharpe uses net monthly long-short returns, sqrt(12); no RF subtraction. "
            "Fold diagnostics assess fixed strategies, not fitted models."
        ),
    )
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    manifest = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.iterdir())
        if p.is_file()
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return report


def main() -> None:
    """Accept explicit symbol/path bindings; retain raw sources outside public summaries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {symbol: Path(path) for symbol, path in json.loads(args.sources.read_bytes()).items()}
    print(json.dumps(run_study(paths, args.output)))


if __name__ == "__main__":
    main()
