# Validation of retained research executions

The validation command connects a saved monthly backtest to the existing walk-forward,
purged-split and Newey-West implementations. It verifies the artifact closure and declared
session coverage, recomputes net returns from account NAVs, and retains the full-sample
diagnostic plus test-block statistics. It does not execute the strategy again.

Create a JSON request with the actual monthly result reference from an experiment receipt:

```json
{
  "schema_version": "research-validation-request-v1",
  "result": {"sha256": "<monthly result SHA-256>", "size_bytes": 1234, "media_type": "application/json"},
  "initial_train_size": 60,
  "test_size": 20,
  "hac_lags": 3,
  "embargo_seconds": 86400,
  "correction": "none"
}
```

Replace the reference, including its exact byte size, and choose the statistical settings
before assessing results. The numbers above illustrate configuration, not a recommended
research design.

```powershell
uv run python -m factorforge.validation.research --request validation-request.json --artifacts artifacts/research --output validation-result.json
```

The result contains both partitions for each contiguous test block: causal expanding
history and a purged research partition with an explicit elapsed-time embargo. Indices
refer to the unchanged return inventory. Adjacent intervals sharing a boundary are purged
under the existing inclusive-overlap policy. Labels here are realized account-return
intervals available at the closing mark; they are not factor holding-cohort labels.

HAC uses only each contiguous test block. Discontiguous training observations are never
concatenated into a fictitious time series. Both partition descriptions share one test
statistic; they are not counted as independent validation results. Insufficient samples
and unsupported split configurations have explicit reasons rather than numeric defaults.

This is validation of a **fixed strategy's net-return path**. No estimator, normalization
or weight is fitted on training indices. It does not yet implement parameter-selection CV,
multiple-testing adjustment, causal promotion decisions or published-factor reproduction.
Those require separately declared research designs and adequate source/data coverage.

Verification includes 39 targeted checks, including existing independent HAC reference
checks. Twelve authored returns produce three test blocks with hand-checked means and
purge/embargo indices; changing training returns leaves their test statistics unchanged.
The actual saved original hybrid result was assessed through the CLI: 41 reachable objects
verified, three full-sample return observations and one test interval. Its fold-level HAC
is explicitly unavailable because one observation is insufficient. Replay returned the
same result with model and backtest dispatch disabled.
