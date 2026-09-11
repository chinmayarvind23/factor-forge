# Results

The browser/API brief flow, PostgreSQL persistence, LangGraph recovery and data foundation are
implemented. The original fixture has a replayable bundle with verified inputs and code.
There are no completed research benchmarks yet.
The target architecture in the design documents must not be interpreted as measured behavior.

| Measure | Evidence status |
| --- | --- |
| Autonomous research completion | Unmeasured; 45-case suite not frozen |
| Published-factor reproduction | Unmeasured; paper/data/tolerance records not frozen |
| FactorSpec extraction accuracy | Unmeasured; extraction baseline not implemented |
| Benchmark lineage completeness | Unmeasured; no benchmark runs |
| Agent/tool spans | Unmeasured; tracing not implemented |
| Paired research runtime | Unmeasured; workload not frozen |
| Average LLM cost per paper | Unmeasured; no model-call billing records |

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
