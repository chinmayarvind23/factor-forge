# Original monthly planning inputs

These are synthetic inputs for a conditional source-to-target calculation: 52 facts for
eight securities, two monthly requests and equal/value portfolio policies. No observed
market dataset, published-factor label, expected output or paper passage is included.

`source.json` has SHA256
`f7641c0ded03e8825727ff1e274702a16ddc09bad631527098eeca74e067c94b` (12,340 bytes).
It retains later restatements, duration contexts and a May numerator published after formation.
Those records exercise selection rules; the command receives the raw source without gold
signals or target weights. Decimal values are strings.

The requests bind the original authored decision pairs in `declared-decisions.json`. That
descriptor is not a complete exchange calendar. The example uses supplied formation/trade
instants and does not prove calendar admission, funding, fills or a continuous backtest.

Run from the repository root:

```console
uv run --locked python -m factorforge.factors.monthly_command --source data/fixtures/monthly-signals-v1/source.json --request data/fixtures/monthly-signals-v1/april-request.json --portfolio data/fixtures/monthly-signals-v1/equal_weight.json --missing-signal fail --output artifacts/local/monthly-april
```

For May, substitute `may-request.json`. With `--missing-signal fail`, the missing formation-time
observation produces a recorded failure and exit status one. An explicit
`--missing-signal exclude_at_formation` permits exclusion before bucket construction. Substitute
`value_weight.json` to apply the separate capitalization weighting policy. Each invocation
creates a new attempt; it does not replace earlier failed outcomes.

The original synthetic content in this directory may be copied, modified and redistributed
for any purpose. This fixture permission does not change the code license or grant rights in
third-party papers or provider data.
