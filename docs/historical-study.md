# Historical signal study

The saved study runs 15 predeclared price-based signals at 0, 10 and 25 basis points
of one-way turnover cost: **45 completed experiments**. Input consists of **30,192
daily observations** for AAPL, MSFT, IBM, JPM, XOM, CVX, WMT and PG, from 2010 through
2024. The complete grid is retained; no outcome selected the published case inventory.

Each experiment has 166 monthly holding intervals, nine expanding walk-forward test
blocks, a matching purged partition with 31-day embargo, and a Bartlett Newey-West
mean diagnostic with three monthly lags. These are fixed-strategy diagnostics, not
training-fold model fitting or 45 independent statistical discoveries.

Signals cover skipped-month momentum, reversal, low volatility, downside variation,
moving-average trend and maximum daily return. `momentum_12_skip1` divides the close
one month before formation by the close 12 months before formation: 11 return months.
All scores use formation-known price history. Entry is delayed until the first session's
close of the next month; exit/rebalance occurs at the following month's first close.

The mathematical portfolio assigns +0.5 to each of the top two stocks and -0.5 to
each of the bottom two, with deterministic symbol tie-breaking. Target dollar positions
use pre-trade NAV. Fees reduce cash; drifted holdings determine subsequent turnover.
Final liquidation pays closing costs. Computation uses float64, independently tested
against hand accounts. This path is separate from the exact raw-price execution engine.

The universe is a retrospective selection of eight surviving stocks, and Yahoo adjusted
prices are a current historical vintage. This study does not supply historical membership,
fundamentals, broker fills, borrow availability, financing or margin simulation. Results
are exploratory and do not measure published-factor reproduction or autonomous LLM runs.
The independently verified LEAN reference cases retain their own scope.

## Reproduce and inspect

Capture the fixed eight-stock universe, or supply a JSON mapping from ticker to an
archived Yahoo chart-response file. Source symbol,
currency, calendar alignment and finite positive adjusted closes are checked before scoring.
Raw sources remain local; the public report contains derived summary metrics.

```powershell
uv run python -m factorforge.data.yahoo_capture --output artifacts/historical-sources
uv run python -m factorforge.evaluation.historical_study --sources artifacts/historical-sources/sources.json --output artifacts/historical-study
uv run python scripts/verify_historical_study.py artifacts/historical-study
uv run python scripts/build_historical_report.py --input artifacts/historical-study/report.json --output dist/space/historical-study.html
```

The downloader archives raw responses, request URLs, capture times, HTTP status and
SHA-256 identities. It uses a fresh directory, bounded response sizes and one request
per symbol; access failures stop capture and retain a failure receipt. `sources.json`
is published only after all eight inputs pass the aligned-panel checks. This command
does not run experiments. Provider revisions can change newly downloaded bytes and
results; the published study identifies its original vintage in the
[frozen configuration](../reports/evidence/historical-freeze.json) and
[artifact manifest](../reports/evidence/historical-manifest.json). Review provider terms
for your use; the repository publishes derived results and hashes, not raw market data.

The output includes source snapshots, Parquet data, frozen configuration, implementation
and validation code, every experiment's scores/weights/returns/fees, fold indices, HAC
results, summary and SHA-256 manifest. **7,516 actual local OpenTelemetry spans** record
the study, experiment and rebalance operations. They are backtest execution spans;
hosted LangSmith readback and LLM cost are separate measurements.

See the [complete summary](../reports/historical-study-v1.json) and
[interactive report](https://chinmayarvind-factorforge.static.hf.space/historical-study.html).
