# Results

The browser/API brief flow, PostgreSQL persistence, LangGraph recovery and data foundation are
implemented. The original fixture has a replayable bundle with verified inputs and code.
There are no completed research benchmarks yet.
The target architecture in the design documents must not be interpreted as measured behavior.

| Measure | Evidence status |
| --- | --- |
| Autonomous research completion | Unmeasured; 45-case suite not frozen |
| Published-factor reproduction | Unmeasured; paper/data/tolerance records not frozen |
| FactorSpec extraction accuracy | Unmeasured; source-extraction pipeline under development |
| Benchmark lineage completeness | Unmeasured; no benchmark runs |
| Agent/tool spans | Unmeasured; tracing not implemented |
| Paired research runtime | Unmeasured; workload not frozen |
| Average LLM cost per paper | Unmeasured; local protocol calls have no dollar-cost measurement |

Engineering smoke tests establish package/build correctness only. Synthetic fixtures will be
reported separately from published-factor replication. Missing measurements are not zero scores.

At commit `ec9503d`, a clean Windows checkout passed 281 Python tests with 96.36% statement/branch
coverage. Two explicit skips cover unavailable audited DVC restoration and a POSIX-only FIFO
test. Another 49 artifact tests passed on Linux, with two Windows-only skips. Combining those
actual platform runs gives 97.997% coverage, including 100% for the bundle, catalog and
point-in-time selector. The suite includes real PostgreSQL failure/restart, RSA verification,
cancellation, artifact corruption and fixture-permission checks.
Nine Bun tests cover browser response/retry handling. Desktop/mobile Playwright checks exercise
real API submission and interrupted-request recovery. Workflow artifacts preserve browser evidence.

The same checkout created and replayed its saved fixture bundle and published/read back that
manifest through PostgreSQL. It preserves the unknown exit outcome and excludes future filings
from formation-time selection. It does not calculate a backtest or establish full research lineage.

Hosted Linux Python and web jobs pass. The complete release gate is blocked by the separate
[DVC dependency audit](../tools/dvc/README.md): diskcache has an unresolved advisory, and the
gate prevents DVC execution. An earlier real empty-cache restore passed before that finding;
it is functional evidence only. Live Cognito, S3 and deployment remain unverified. These
engineering checks do not measure research quality.

## Retrieval development pilot

At clean commit `42c66c2`, the frozen [three-paper pilot](../data/literature/three-paper-pilot-v1/README.md)
ran after 124 focused checks passed. BM25 ranked the relevant paper first for all six answerable
queries: Recall@3 and MRR@3 were both 1.0. It returned irrelevant results for all three no-relevant
queries, seven documents in total: false-positive query rate 1.0, abstention rate 0.0.
The [complete per-query report](../reports/retrieval/three-paper-bm25-v1.json) preserves both outcomes.
The corpus and judgments were committed before evaluation, and no threshold was tuned afterward.

These are three original summaries and manually targeted queries, not a representative retrieval
benchmark or a published-factor replication result. With three documents and `k=3`, Recall@3 alone
offers little discrimination. First-rank results and negative-query behavior are reported separately.
The saved local evaluation record is `60aa85c6e2df6b734053c98d085752380cef080df13ea52bed40edaf59310518`;
it preserves input bytes, configuration, code snapshots, environment and results.

## Local model protocol evidence

A single 32,768-context protocol call timed out during model loading after 120.55 seconds.
A separately versioned 4,096-context, 128-output-token probe returned the requested JSON in
32.34 seconds, with 39 reported prompt tokens and 10 output tokens. Both attempts retain evidence.
The smaller probe establishes local delivery only. Neither is a paper extraction or a controlled
performance comparison, and neither measures dollar cost.
