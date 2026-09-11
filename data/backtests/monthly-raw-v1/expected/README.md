# Original reference outputs

These files contain independently calculated expected values for the original monthly
simulator inputs in `../inputs`. They are comparison references and must never enter the
strategy's selection, sizing or accounting inputs.

`declaration.json` binds the input bytes and explicit execution/metric conventions.
`trace.json` records all mandatory balance-sheet observations and the two atomic fee batches.
`metrics.json` retains exact rational returns, means, variance, turnover and drawdown,
plus a 120-digit square-root calculation and its 50-digit Sharpe representation.
`freeze.json` identifies the original inputs, expected files and independent generator.

The annualization factor is 252, variance uses ddof=1, and drawdown samples the baseline and
session closes. Entry fees belong to the first genuine close-to-close interval. The larger
entry-open loss is retained separately. The absolute 1e-40 comparison tolerance concerns
finite decimal representation; it is not an empirical benchmark tolerance.

The calendar, prices, score observations, permissions and zero benchmark/risk-free intervals
are original fictional data. The three-interval Sharpe is an arithmetic test result, with no
claim of research validity or real-market performance. The full v3 strategy specification
must be bound separately before an admitted execution can be compared with this reference.
