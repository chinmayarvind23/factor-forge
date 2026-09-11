# Results

The local browser/API flow is implemented. There are no completed research benchmarks yet.
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

Current engineering validation includes 22 Python tests and 9 Bun tests, plus four Playwright
cases covering real API submission and interrupted-request recovery on desktop and mobile.
The foundation and API commits passed the hosted Linux quality workflow. Browser evidence is
recorded by the workflow artifact upload; these are development checks rather than research benchmarks.
