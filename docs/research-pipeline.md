# Research Pipeline

## Purpose

FactorForge uses the full autonomous-research sequence from the AI Engineering from Scratch capstone as the research lifecycle. The production system adds typed contracts, agent orchestration, sandboxing, reproducibility, finance-specific validation, observability, and release gates around that sequence.

The nine stages are not isolated demos. They compose into one stateful research system.

## Stage map

| Research stage | FactorForge implementation |
|---|---|
| Language Model Evaluation Harness | Frozen eval cases, deterministic graders, DeepEval semantic graders, outcome and execution-path scorecards, regression gates |
| Hypothesis Generator | Multiple typed `Hypothesis` candidates, novelty/specificity/testability scoring, duplicate filtering, `FactorSpec` generation |
| Literature Retrieval | Elasticsearch lexical/hybrid search, dense retrieval comparison, citation relationships, provenance, literature MCP |
| Experiment Runner | Typed `ExperimentSpec`, generated code hash, Docker/EKS sandbox, deterministic seeds, time/CPU/RAM/PID/network limits, artifacts and logs |
| Result Evaluator | Point-in-time checks, Sharpe, Sortino, drawdown, IC, turnover, transaction costs, walk-forward, purged CV, HAC statistics, robustness verdicts |
| Paper Writer | Evidence-constrained research report from accepted artifacts, citations, limitations, experiment IDs, and reproduction commands |
| Critic Loop | Bounded Deep Agent critic that identifies weaknesses, proposes the next research action, and stops under convergence, budget, and plateau rules |
| Iteration Scheduler | Ranked research branches, UCB-style exploration/exploitation, pruning, experiment budgets, parallel slots, and hard stop conditions |
| End-to-End Research Demo | The complete typed pipeline from idea through evidence, experiments, critique, LEAN verification, report, lineage, and reproduction bundle |

## End-to-end flow

```text
natural-language investment idea
        |
        v
normalize ResearchBrief
        |
        v
literature retrieval
        |
        v
hypothesis generator
        |
        v
typed FactorSpec
        |
        v
research planner
        |
        v
experiment runner
        |
        v
result evaluator
        |
        v
critic loop
   +----+----+
   |         |
iterate   promote
   |         |
scheduler    v
   |     LEAN verification
   |         |
   +---------+
        |
        v
paper writer
        |
        v
research memory + failed-experiment ledger
        |
        v
reproducible report
```

## Evaluation harness around the graph

The evaluation harness observes every stage rather than only the final report.

```text
                      EVALUATION HARNESS
+------------------------------------------------------------+
| idea -> literature -> hypotheses -> experiments -> critic |
|                         |                       |           |
|                         +-> validators <- scheduler        |
|                                     |                      |
|                              LEAN verification             |
|                                     |                      |
|                                   report                   |
+------------------------------------------------------------+

Outcome graders
+
Execution-path graders
+
Quant correctness graders
+
Security/sandbox graders
+
Cost/latency/trace graders
```

A research result can have a strong Sharpe ratio and still fail the system evaluation because the execution path used future information, skipped a required validator, violated the sandbox, exceeded a budget, or produced incomplete lineage.

## Hypothesis generation

The system generates multiple candidates before paying for expensive experiments.

A starting ranking function can be:

```text
score(h) =
  0.4 * novelty(h)
+ 0.3 * specificity(h)
+ 0.3 * testability(h)
```

The weights are versioned configuration and are evaluated rather than treated as universal constants.

The LLM proposes the hypothesis. Typed schemas and deterministic rules decide whether it is executable.

## Literature retrieval

Literature retrieval supports semantic relevance and exact finance terminology.

```text
BM25
+
dense retrieval
+
citation-neighborhood evidence
        |
        v
deduplication
        |
        v
fusion / reranking
        |
        v
paper evidence with stable IDs
```

Retrieval is evaluated with a frozen qrels set.

## Experiment runner

The experiment runner is an execution system, not a model call.

```text
agent proposes experiment
        |
        v
Pydantic ExperimentSpec
        |
        v
capability + policy validation
        |
        v
SQS
        |
        v
Docker / EKS Job
        |
        +--> CPU limit
        +--> RAM limit
        +--> PID limit
        +--> wall-clock deadline
        +--> network policy
        +--> filesystem policy
        |
        v
result + logs + artifacts + lineage
```

## Result evaluator

The LLM does not decide whether portfolio accounting is correct.

```text
gross_return_t = w_(t-1)^T r_t
turnover_t = sum_i |w_i,t - w_i,t-1|
transaction_cost_t = turnover_t * cost_per_unit
net_return_t = gross_return_t - transaction_cost_t
```

A structured research verdict is selected from:

```text
SUPPORTED
UNSUPPORTED
UNSTABLE
INCONCLUSIVE
INVALID_DATA
INVALID_METHOD
VERIFICATION_DISAGREEMENT
```

## Critic loop

The critic receives verified evidence, not only prose generated by another model.

```text
Finding:
The signal has predictive content but monthly turnover removes the edge.

Evidence:
Experiment 28
gross Sharpe = 1.44
net Sharpe = 0.31

Next action:
Test a slower rebalance schedule.

Do not repeat:
The same signal and same rebalance configuration without a material change.
```

The result is added to research state and memory.

## Iteration scheduler

A UCB-style scheduler can prioritize branches under a fixed experiment budget:

```text
UCB_i = mean_reward_i + c * sqrt(ln(N) / n_i)
```

The scheduler is bounded by deterministic limits:

```text
maximum experiments
maximum wall time
maximum LLM cost
maximum cloud compute
maximum critic rounds
```

## Paper writer

The report writer is intentionally last.

It receives only accepted evidence:

```text
paper provenance
FactorSpec
dataset version
experiment IDs
validation results
LEAN result
critic decisions
known failures
limitations
```

The report is derived from the research record. It is not the system of record.

## End-to-end demonstration

The final demo makes the lifecycle visible:

```text
Research idea
    |
Literature
    |
Hypotheses
    |
FactorSpec
    |
Experiments
    |
Validation
    |
Critique and iteration
    |
Independent LEAN verification
    |
Report
    |
Lineage bundle and reproduction command
```

The demo also includes a failure case so autonomy means correct stopping and refusal as well as successful research.
