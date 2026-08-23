# Quantitative Research Methodology

## Purpose

The research agent may propose ideas. Quantitative claims are accepted only through deterministic research code and declared methodology.

## Point-in-time correctness

The core invariant is:

```text
information_used_at_t <= information_available_at_t
```

A factor calculation uses the publication/availability timestamp, not merely the economic period the data describes.

Examples:

- a quarterly filing is unavailable before publication,
- historical index membership cannot be replaced with today's membership,
- splits/dividends require point-in-time corporate-action handling,
- delisted securities cannot silently disappear from history.

## Lookahead leakage tests

Each feature can carry:

```text
source timestamp
availability timestamp
effective timestamp
formation timestamp
trade timestamp
```

A basic invariant is:

```python
assert availability_ts <= formation_ts < trade_ts
```

## Walk-forward validation

```text
train [----]
              validate [--]
                         test [--]

train [--------]
                  validate [--]
                             test [--]
```

Parameter/model selection sees only past data.

## Purged cross-validation and embargo

When labels overlap in time, ordinary K-fold validation leaks information across folds.

Purging removes training examples whose information interval overlaps the validation/test interval. Embargo removes an additional interval after that fold.

Purge and embargo lengths are configuration and evidence.

## Returns and costs

Gross portfolio return:

```text
r_gross,t = w_(t-1)^T r_t
```

Simple linear cost model:

```text
turnover_t = sum_i |w_i,t - w_i,t-1|
cost_t = turnover_t * cost_per_unit
r_net,t = r_gross,t - cost_t
```

More detailed slippage may depend on spread, volatility, and participation rate. Every added parameter must be declared.

## Sharpe ratio

```text
Sharpe = sqrt(A) * mean(r) / std(r)
```

`A` is the annualization factor consistent with return frequency.

## Sortino ratio

```text
Sortino = annualized_mean_excess_return / annualized_downside_deviation
```

The downside threshold is explicit.

## Maximum drawdown

For wealth index `W_t`:

```text
peak_t = max(W_0 ... W_t)
drawdown_t = W_t / peak_t - 1
MDD = min_t drawdown_t
```

## Information coefficient

For cross-sectional factors:

```text
IC_t = corr(signal_t, future_return_t)
```

Use Pearson or rank/Spearman as declared.

## HAC/Newey-West t-stat

Factor returns and overlapping portfolios can have autocorrelation. The mean-return t-stat uses a heteroskedasticity and autocorrelation consistent variance estimate rather than assuming independent observations.

Generic estimator:

```text
Var_HAC(mean) =
  1/T * [gamma_0 + 2 * sum_{l=1..L} k(l,L) * gamma_l]
```

Bartlett kernel:

```text
k(l,L) = 1 - l/(L+1)
```

Then:

```text
t = mean(r) / sqrt(Var_HAC(mean))
```

The lag rule is versioned.

## Multiple testing

Autonomous research can generate many hypotheses. A low p-value after trying hundreds of variants is weaker evidence than the same p-value for a predeclared test.

The system records:

- hypotheses proposed,
- hypotheses executed,
- selection rule,
- parameter sweeps,
- confirmatory vs exploratory status.

Where appropriate, report false-discovery controls or deflated/selection-aware statistics.

## Robustness

Promoted results are challenged across:

- subperiods,
- regimes,
- universe definitions,
- transaction-cost assumptions,
- signal lags,
- seeds for stochastic methods,
- weighting schemes,
- neutralization choices.

## Independent LEAN verification

A candidate that passes the fast engine is translated into a canonical strategy spec and rerun through LEAN.

Compare:

- return series shape,
- turnover,
- gross/net performance,
- Sharpe,
- drawdown,
- trade count,
- exposure,
- rebalance behavior.

A disagreement is a first-class result, not something to average away.

## Published-factor reproduction tolerance

Each factor case declares its tolerance before the evaluated run.

```yaml
factor_id: example
reference:
  paper_id: ...
  expected_sign: positive
tolerance:
  sharpe_abs_delta_max: 0.20
  t_stat_abs_delta_max: 0.50
  correlation_min: 0.80
required:
  - expected_sign
  - return_series_correlation
  - sharpe_tolerance
  - t_stat_tolerance
```

Exact values vary by factor and available data. They are frozen before evaluation.

## Research verdicts

```text
SUPPORTED
UNSUPPORTED
UNSTABLE
INCONCLUSIVE
INVALID_DATA
INVALID_METHOD
VERIFICATION_DISAGREEMENT
```

The report explains the evidence behind the verdict.

## Research reward and finance safeguards

The agentic-learning reward is not a direct optimization of backtest return.

Hard finance-methodology failures override soft utility.

Examples:

```text
lookahead leakage
invalid as-of join
required transaction-cost model skipped
required walk-forward/purged validation skipped
metric implementation mutated by the policy
```

This prevents the policy from learning that a misleading backtest is a successful research action.
