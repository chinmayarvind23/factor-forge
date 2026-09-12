# Project claims and evidence

FactorForge connects investment ideas to literature, typed hypotheses, compatible
hybrid strategies, bounded experiments and retained research decisions. The links
below connect the implementation to the specific results that have been measured.

## Resume-ready project description

**FactorForge | Python, LangGraph, Deep Agents, LangSmith, Polars, LEAN, MLflow,
Neo4j, PyTorch/TRL, PostgreSQL, Docker, AWS, Hugging Face**

- Built a quantitative-research agent connecting natural-language investment ideas
  to literature, structured hypotheses, hybrid strategies, sandboxed backtests and
  iterative decisions; exercised its numerical research layer with **45 historical
  signal-and-cost experiments across 30,192 daily observations**.
- Developed validation with multi-paper synthesis, walk-forward and purged splits,
  transaction-cost modeling and statistical diagnostics, evaluating **15 price-based
  signals across 3 cost settings** and achieving **100% agreement across 13 portfolio
  valuations and 4 trade fills, including fees**, against an independent LEAN reference.
- Built auditable research memory and reviewed training-data exports, verified
  **64 historical-study files through MLflow readback**, traced **7,516 backtest
  execution spans**, and deployed an interactive dashboard on **Hugging Face**.

The stack includes optional integration paths. PyTorch/TRL training is implemented
but has not been executed; AWS has adapters and setup guidance, while the public
deployment uses free Hugging Face hosting. See [stack roles and status](stack-status.md).

## Inspect the evidence

| Claim | Saved evidence | Implementation |
|---|---|---|
| Literature-to-research workflow | [Operator guide](research-command.md), [multi-paper synthesis](source-synthesis.md) | [Research orchestration](../src/factorforge/orchestration/) |
| 45 experiments; 30,192 daily observations | [Every case summary](../reports/historical-study-v1.json), [frozen study](../reports/evidence/historical-freeze.json) | [Study runner](../src/factorforge/evaluation/historical_study.py), [source capture](../src/factorforge/data/yahoo_capture.py) |
| 13 valuations and 4 fills match LEAN | [Independent comparison](../data/verification/lean-execution-v1/comparison.json) | [LEAN execution](../infra/lean/execution/README.md) |
| 64 historical MLflow files | [Export receipt](../reports/evidence/historical-mlflow.json), [replay receipt](../reports/evidence/historical-mlflow-replay.json) | [Exporter](../tools/tracking/historical_export.py) |
| 7,516 backtest spans | [Study report](../reports/historical-study-v1.json), [63-file manifest](../reports/evidence/historical-manifest.json) | [Span export and instrumentation](../src/factorforge/evaluation/historical_study.py) |
| Free deployed demonstration | [Live dashboard](https://chinmayarvind-factorforge.static.hf.space/), [recorded walkthrough](assets/demo.mp4) | [Demo source](../apps/demo/), [recording receipt](assets/demo-recording.json) |
| Reviewed SFT/DPO path | [Training contract and commands](../tools/training/README.md) | [Preparation](../tools/training/prepare.py), [local trainer](../tools/training/train.py) |

The 64-file historical export contains the 63 manifest-listed artifacts plus the
manifest. The older 64-object research projection is a separate engineering case;
the counts are not combined. Public receipts record completed local verification;
they are not independent attestations or a substitute for access to the underlying
private raw-data archive. The download and verification commands let an operator
produce and inspect a new local study.

The 45 numerical cases are a 15-by-3 signal/cost grid on a fixed retrospective
eight-stock universe. They do not measure 45 autonomous literature-to-backtest runs,
15 published-factor replications, extraction accuracy, or end-to-end LLM runtime/cost.
Those original target measurements remain separate. No new research evaluation was
performed for this presentation update.
