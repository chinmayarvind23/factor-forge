"""Bind net-return diagnostics to retained monthly execution paths and exact session calendars."""

from typing import Annotated, Literal

from pydantic import Field

from factorforge.backtests.monthly import MonthlyRun
from factorforge.backtests.performance import compute_performance
from factorforge.data.artifacts import ArtifactStore, reference, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.calendar import SessionCalendar, plan_formations
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.validation.hac import HACRequest, HACResult, hac_mean


class MonthlyHACRequest(Contract):
    """A verified result artifact, lag and correction fully identify this net-return diagnostic."""

    schema_version: Literal["monthly-hac-request-v1"] = "monthly-hac-request-v1"
    result: ArtifactRef
    lags: Annotated[int, Field(ge=0, le=120)]
    correction: Literal["none", "n_over_n_minus_one"]


class MonthlyHACResult(Contract):
    """Calendar-index spacing is explicit; three original observations are not factor evidence."""

    schema_version: Literal["monthly-hac-result-v1"] = "monthly-hac-result-v1"
    cadence: Literal["consecutive_declared_trading_sessions"] = (
        "consecutive_declared_trading_sessions"
    )
    return_kind: Literal["net_raw_portfolio_return"] = "net_raw_portfolio_return"
    request: MonthlyHACRequest
    diagnostic: HACResult | None
    reason: Literal["EXPERIMENT_NOT_COMPLETED", "INSUFFICIENT_HAC_SAMPLE"] | None


def _read(store: ArtifactStore, ref: ArtifactRef, limit: int) -> bytes:
    """Keep expected metadata separate from the provider's detached reference object."""
    expected = ArtifactRef.model_validate(ref)
    if expected.media_type != "application/json" or not 0 < expected.size_bytes <= limit:
        raise ValueError("Unsupported validation artifact")
    raw = store.get(expected.model_copy(deep=True))
    if type(raw) is not bytes:
        raise ValueError("Validation artifact must contain bytes")
    verify_bytes(raw, expected)
    return raw


def validate_monthly_hac(request: MonthlyHACRequest, artifacts: ArtifactStore) -> MonthlyHACResult:
    """Recompute returns from verified account closes with complete declared session coverage.

    Artifact integrity is not authorization or proof of market-data accuracy. A durable worker
    must supply its canonical settled result reference. This adapter never executes a strategy.
    """
    request = MonthlyHACRequest.model_validate(request)
    try:
        raw = _read(artifacts, request.result, 2**20)
        run = MonthlyRun.model_validate_json(raw)
        if run.canonical_bytes() != raw:
            raise ValueError("Monthly result must be canonical")
        diagnostic = None
        reason: Literal["EXPERIMENT_NOT_COMPLETED", "INSUFFICIENT_HAC_SAMPLE"] | None = None
        if run.status != "completed":
            reason = "EXPERIMENT_NOT_COMPLETED"
        else:
            spec = run.request.spec
            calendar = SessionCalendar.model_validate_json(
                _read(artifacts, spec.timing.calendar, 8 * 2**20)
            )
            plans = plan_formations(
                calendar,
                spec.timing,
                start=spec.evaluation.sample_start,
                end=spec.evaluation.sample_end,
            )
            if not plans or run.path is None:
                raise ValueError("Completed result needs an executable formation and path")
            closes = tuple(
                session.closes_at
                for session in calendar.sessions
                if session.closes_at >= plans[0].formation_at
                and session.session_date <= spec.evaluation.sample_end
            )
            if closes != run.session_closes:
                raise ValueError("Execution omits or changes declared calendar sessions")
            performance = compute_performance(
                run.path,
                annualization=spec.evaluation.annualization,
                risk_free=None,
                execution_batches=None,
            )
            values = tuple(row.net_return for row in performance.intervals)
            if len(values) < 2 or request.lags >= len(values):
                reason = "INSUFFICIENT_HAC_SAMPLE"
            else:
                diagnostic = hac_mean(
                    HACRequest(values=values, lags=request.lags, correction=request.correction)
                )
        result = MonthlyHACResult(request=request, diagnostic=diagnostic, reason=reason)
        content = result.canonical_bytes()
        expected = reference(content, "application/json", 2**20)
        if artifacts.put(content, media_type="application/json") != expected:
            raise ValueError("Diagnostic publication identity differs")
        return result
    except Exception:
        raise ResearchError(
            "VALIDATION_EVIDENCE_INVALID", "Validation evidence cannot be verified.", 409
        ) from None
