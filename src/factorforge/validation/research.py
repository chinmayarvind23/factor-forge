"""Bind walk-forward and purged fold diagnostics to a complete retained monthly execution."""

import argparse
import json
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from factorforge.backtests.monthly import MonthlyRun
from factorforge.backtests.performance import compute_performance
from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.factors import Contract
from factorforge.domain.performance import ReturnInterval
from factorforge.factors.hybrid import publish
from factorforge.lineage.closure import verify_closure
from factorforge.validation.hac import HACRequest, HACResult, hac_mean
from factorforge.validation.monthly import (
    MonthlyHACRequest,
    MonthlyHACResult,
    _read,
    validate_monthly_hac,
)
from factorforge.validation.splits import LabelPeriod, ValidationFold, purged_fold, walk_forward


class ValidationRequest(Contract):
    """Predeclared split and covariance choices bind diagnostics to one exact execution."""

    schema_version: Literal["research-validation-request-v1"] = "research-validation-request-v1"
    result: ArtifactRef
    initial_train_size: Annotated[int, Field(ge=2, le=10000)]
    test_size: Annotated[int, Field(ge=1, le=10000)]
    hac_lags: Annotated[int, Field(ge=0, le=120)]
    embargo_seconds: Annotated[int, Field(ge=0, le=366 * 86400)]
    correction: Literal["none", "n_over_n_minus_one"] = "none"


class FoldDiagnostic(Contract):
    """Both partitions share the same contiguous test block; it is assessed exactly once."""

    walk_forward: ValidationFold
    purged: ValidationFold
    test_diagnostic: HACResult | None
    reason: Literal["INSUFFICIENT_HAC_SAMPLE"] | None


class ResearchValidation(Contract):
    """Fixed-strategy diagnostics are not fitted-model CV, independent tests or promotion."""

    schema_version: Literal["research-validation-result-v1"] = "research-validation-result-v1"
    scope: Literal["fixed_strategy_net_return_diagnostics"] = (
        "fixed_strategy_net_return_diagnostics"
    )
    request: ValidationRequest
    full_sample: MonthlyHACResult
    periods: Annotated[tuple[LabelPeriod, ...], Field(max_length=10000)]
    folds: Annotated[tuple[FoldDiagnostic, ...], Field(max_length=100)]
    reason: (
        Literal[
            "EXPERIMENT_NOT_COMPLETED",
            "INSUFFICIENT_SPLIT_SAMPLE",
            "SPLIT_CONFIGURATION_UNSUPPORTED",
        ]
        | None
    )


def assess_folds(
    intervals: tuple[ReturnInterval, ...],
    request: ValidationRequest,
) -> tuple[FoldDiagnostic, ...]:
    """Assess contiguous test blocks once; never concatenate the purged training series."""
    request = ValidationRequest.model_validate(request)
    if not 2 <= len(intervals) <= 10000:
        raise ValueError("Bounded complete intervals are required")
    intervals = tuple(ReturnInterval.model_validate(row) for row in intervals)
    if any(left.end_at != right.start_at for left, right in pairwise(intervals)):
        raise ValueError("Return intervals must be contiguous")
    periods = tuple(
        LabelPeriod(start=row.start_at, end=row.end_at, available_at=row.end_at)
        for row in intervals
    )
    diagnostics = []

    forward = walk_forward(
        periods,
        initial_train_size=request.initial_train_size,
        test_size=request.test_size,
    )
    purged = tuple(
        purged_fold(
            periods,
            test_start=fold.test[0],
            test_stop=fold.test[-1] + 1,
            embargo_seconds=request.embargo_seconds,
        )
        for fold in forward
    )
    for fold, cross_validation in zip(forward, purged, strict=True):
        values = tuple(intervals[index].net_return for index in fold.test)
        enough = len(values) >= 2 and request.hac_lags < len(values)
        diagnostics.append(
            FoldDiagnostic(
                walk_forward=fold,
                purged=cross_validation,
                test_diagnostic=hac_mean(
                    HACRequest(
                        values=values,
                        lags=request.hac_lags,
                        correction=request.correction,
                    )
                )
                if enough
                else None,
                reason=None if enough else "INSUFFICIENT_HAC_SAMPLE",
            )
        )
    return tuple(diagnostics)


def validate_research(request: ValidationRequest, artifacts: ArtifactStore) -> ResearchValidation:
    """Recompute account returns, verify session coverage and retain time-aware test statistics.

    The strategy is fixed: no parameters are fitted and training indices are eligibility
    evidence. Purged partitions can include future training indices and are explicitly
    research diagnostics. HAC never compresses discontiguous training observations into
    a false contiguous sample. No p-value, independence claim or promotion is inferred.
    """
    request = ValidationRequest.model_validate(request)
    verify_closure(request.result, artifacts)
    full = validate_monthly_hac(
        MonthlyHACRequest(
            result=request.result, lags=request.hac_lags, correction=request.correction
        ),
        artifacts,
    )
    run = MonthlyRun.model_validate_json(_read(artifacts, request.result, 2**20))
    periods: tuple[LabelPeriod, ...] = ()
    diagnostics: list[FoldDiagnostic] = []
    reason: (
        Literal[
            "EXPERIMENT_NOT_COMPLETED",
            "INSUFFICIENT_SPLIT_SAMPLE",
            "SPLIT_CONFIGURATION_UNSUPPORTED",
        ]
        | None
    ) = None
    if run.status != "completed":
        reason = "EXPERIMENT_NOT_COMPLETED"
    else:
        assert run.path is not None
        performance = compute_performance(
            run.path,
            annualization=run.request.spec.evaluation.annualization,
            risk_free=None,
            execution_batches=None,
        )
        periods = tuple(
            LabelPeriod(start=row.start_at, end=row.end_at, available_at=row.end_at)
            for row in performance.intervals
        )
        if len(periods) <= request.initial_train_size:
            reason = "INSUFFICIENT_SPLIT_SAMPLE"
        else:
            try:
                diagnostics = list(assess_folds(performance.intervals, request))
            except ValueError:
                reason = "SPLIT_CONFIGURATION_UNSUPPORTED"
    result = ResearchValidation(
        request=request,
        full_sample=full,
        periods=periods,
        folds=tuple(diagnostics),
        reason=reason,
    )
    verify_closure(publish(result, artifacts), artifacts)
    return result


def main() -> None:
    """Assess saved evidence without redispatch and exclusively create the output receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.request.open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("Validation request exceeds limit")
    artifacts = LocalArtifactStore(args.artifacts)
    result = validate_research(ValidationRequest.model_validate_json(raw), artifacts)
    with args.output.open("xb") as output:
        output.write(result.canonical_bytes())
    print(
        json.dumps(
            {
                "result": publish(result, artifacts).model_dump(mode="json"),
                "folds": len(result.folds),
                "reason": result.reason,
            }
        )
    )


if __name__ == "__main__":
    main()
