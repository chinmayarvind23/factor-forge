# Results

The browser/API brief flow, PostgreSQL persistence and actual LangGraph recovery are implemented.
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

Current local engineering validation includes 126 Python tests with 96.99% combined coverage,
including real PostgreSQL failure/restart tests, RSA verification and cancellation checks.
Nine Bun tests cover browser response/retry handling. Desktop/mobile Playwright checks exercise
real API submission and interrupted-request recovery. Workflow artifacts preserve browser evidence.

The foundation, browser and PostgreSQL commits passed hosted Linux CI. An authentication test
exposed a platform-dependent parser assumption; an explicit header-size bound replaced that
assumption and passed the follow-up Linux run. Live Cognito, S3 and deployment have
not been demonstrated. These engineering checks do not measure research quality.
