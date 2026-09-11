"""Polars table admission and partitioning retain exact scalar ordering and rational weights."""

import hashlib
import json
from decimal import Decimal
from fractions import Fraction
from typing import Literal

import polars as pl
from pydantic import ValidationError

from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import CostSpec, PortfolioSpec
from factorforge.domain.targets import (
    BucketPosition,
    CrossSection,
    PositionWeight,
    Rational,
    TargetPlan,
    TradeCost,
    bounded_fraction,
)


def build_targets(
    panel: CrossSection,
    portfolio: PortfolioSpec,
    *,
    missing_signal: Literal["fail", "exclude_at_formation"],
) -> TargetPlan:
    """Partition selected signals; source, point-in-time and funding checks remain separate."""
    try:
        panel = CrossSection.model_validate(panel)
        portfolio = PortfolioSpec.model_validate(portfolio)
        if missing_signal not in {"fail", "exclude_at_formation"}:
            raise ValueError("Missing-signal policy is unsupported")
        observed = {row.security_id: row for row in panel.observations}
        values = sorted(
            {Decimal(row.signal) for row in panel.observations if row.signal is not None}
        )
        ordinals = {value: rank for rank, value in enumerate(values)}
        # Exact Decimal ordinals prevent Float64 or Decimal128 conversion from creating false ties.
        rows = pl.DataFrame(
            {
                "security_id": [row.security_id for row in panel.observations],
                "ordinal": [
                    ordinals[Decimal(row.signal)] if row.signal is not None else None
                    for row in panel.observations
                ],
                "has_cap": [row.capitalization is not None for row in panel.observations],
            },
            schema={"security_id": pl.String, "ordinal": pl.Int64, "has_cap": pl.Boolean},
        )
        frame = pl.DataFrame({"security_id": sorted(panel.universe)}).join(
            rows, on="security_id", how="left", validate="1:1"
        )
        missing = pl.col("ordinal").is_null()
        if portfolio.weighting == "value_weight":
            missing = missing | ~pl.col("has_cap").fill_null(False)
        excluded = tuple(frame.filter(missing).get_column("security_id").sort().to_list())
        if excluded and missing_signal == "fail":
            raise ValueError("Required selected signals are missing")
        frame = frame.filter(~missing).sort("ordinal", "security_id").with_row_index("rank")
        q, r = divmod(frame.height, portfolio.bucket_count)
        if q < portfolio.minimum_bucket_size:
            raise ValueError("Insufficient eligible rows for the declared bucket policy")
        cutoff = r * (q + 1)
        frame = frame.with_columns(
            pl.when(pl.col("rank") < cutoff)
            .then(pl.col("rank") // (q + 1))
            .otherwise(r + (pl.col("rank").cast(pl.Int64) - cutoff) // q)
            .alias("bucket")
        )
        ordered = [
            (str(row[0]), int(row[1])) for row in frame.select("security_id", "bucket").iter_rows()
        ]
        amounts = {
            key: Fraction(Decimal(observed[key].capitalization or "1"))
            if portfolio.weighting == "value_weight"
            else Fraction(1)
            for key, _ in ordered
        }
        totals = [Fraction(0) for _ in range(portfolio.bucket_count)]
        for key, bucket in ordered:
            totals[bucket] = bounded_fraction(totals[bucket] + amounts[key])
        low_sign = -1 if portfolio.direction == "long_high_short_low" else 1
        positions = []
        for key, bucket in ordered:
            sign = (
                low_sign
                if bucket == 0
                else -low_sign
                if bucket == portfolio.bucket_count - 1
                else 0
            )
            positions.append(
                BucketPosition(
                    security_id=key,
                    bucket=bucket,
                    weight=Rational.from_fraction(sign * amounts[key] / totals[bucket]),
                )
            )
        inputs = panel.model_dump(mode="json")
        inputs["universe"] = sorted(inputs["universe"])
        inputs["observations"] = sorted(inputs["observations"], key=lambda row: row["security_id"])
        inputs["missing_signal"] = missing_signal
        return TargetPlan(
            input_sha256=hashlib.sha256(
                json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            portfolio_sha256=portfolio.sha256,
            portfolio=portfolio,
            formation=panel.formation,
            positions=tuple(positions),
            excluded=excluded,
        )
    except (ValueError, TypeError, ValidationError, pl.exceptions.PolarsError):
        raise ResearchError(
            "TARGET_INPUT_INVALID", "Conditional target inputs are invalid.", 422
        ) from None


def estimate_trade_cost(
    targets: TargetPlan, drifted: tuple[PositionWeight, ...], costs: CostSpec
) -> TradeCost:
    """Use one shared pre-trade NAV basis and retain liquidation of absent target identities."""
    try:
        targets = TargetPlan.model_validate(targets)
        costs = CostSpec.model_validate(costs)
        if not isinstance(drifted, tuple) or len(drifted) > 10000:
            raise ValueError("Drifted inventory exceeds its bounds")
        validated = tuple(PositionWeight.model_validate(row) for row in drifted)
        previous = {row.security_id: row.weight.as_fraction() for row in validated}
        if len(previous) != len(validated):
            raise ValueError("Drifted position identities must be unique")
        desired = {row.security_id: row.weight.as_fraction() for row in targets.positions}
        turnover = Fraction(0)
        for key in sorted(previous.keys() | desired.keys()):
            turnover = bounded_fraction(
                turnover + abs(desired.get(key, Fraction(0)) - previous.get(key, Fraction(0)))
            )
        return TradeCost(
            costs=costs,
            turnover=Rational.from_fraction(turnover),
            commission=Rational.from_fraction(turnover * Fraction(costs.commission_bps, 10000)),
            slippage=Rational.from_fraction(turnover * Fraction(costs.slippage_bps, 10000)),
        )
    except (ValueError, TypeError, ValidationError):
        raise ResearchError(
            "TARGET_COST_INVALID", "Conditional cost inputs are invalid.", 422
        ) from None
