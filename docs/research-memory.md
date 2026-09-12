# Research Memory and Failed-Experiment Ledger

## Implemented operator memory

`factorforge-research --workflow` saves verified completion receipts in PostgreSQL's
`research_workflows` table. An owner-scoped literal idea search is available through
`--memory-query`. Each hit links the full request, result, budget and reports, including
held and stopped candidates. Publication is idempotent and follows report verification.
See the [workflow command](research-command.md).

This initial memory is an evidence index. Automatic prompt augmentation, semantic/graph
retrieval, Neo4j materialization and learned trajectory reuse below remain planned.

## Purpose

FactorForge remembers research outcomes so later runs can reuse evidence instead of repeating the same work. The memory system preserves successful experiments, failed experiments, rejected hypotheses, engine disagreements, and methodological invalidations.

The failed-experiment log is a first-class product feature, not a debugging afterthought.

## Canonical experiment ledger

Every experiment appends an immutable record:

```text
experiment_id
run_id
hypothesis_id
parent_experiment_id
factor_spec_version
dataset_version
code_hash
environment_hash
engine
config
seeds
started_at
finished_at
terminal_state
metrics
validation_results
failure_class
failure_fingerprint
critic_decision
keep_or_reject
next_action
artifact_refs
trace_ids
```

Existing ledger entries are never overwritten to make a later result look cleaner. A repair or changed experiment creates a new experiment ID linked to its parent.

## Failure classes

```text
IMPLEMENTATION_FAILURE
DATA_FAILURE
METHODOLOGY_FAILURE
STATISTICAL_FAILURE
ROBUSTNESS_FAILURE
VERIFICATION_DISAGREEMENT
SECURITY_BLOCK
DEPENDENCY_FAILURE
BUDGET_STOP
NEGATIVE_RESULT
```

A failure class carries structured details instead of only free-form text.

## Failure fingerprint

A normalized fingerprint helps the agent recognize that it is about to repeat a known failure.

Example inputs:

```text
factor family
critical FactorSpec fields
failure class
validator name/version
error code
engine
relevant config subset
data version family
```

The fingerprint is used for retrieval and duplicate-research detection. It is not a guarantee that two experiments are identical.

## Reuse policy

Before scheduling a new experiment, the planner checks research memory.

Possible decisions:

```text
REUSE_SUCCESS
REUSE_NEGATIVE_RESULT
RETRY_WITH_CHANGED_ASSUMPTION
RETRY_WITH_CHANGED_IMPLEMENTATION
REVERIFY_ON_NEW_DATA
IGNORE_AS_NONCOMPARABLE
```

A prior failure does not permanently ban a research direction. It changes the burden of proof. A retry must identify what materially changed.

## Examples

### Known transaction-cost failure

A momentum variant produced attractive gross returns but failed after realistic turnover costs.

Later runs should retrieve that result and avoid blindly rerunning the same weighting and rebalance configuration.

### Lookahead failure

A factor appeared strong until the point-in-time validator detected an invalid reporting lag.

That result is stored as `METHODOLOGY_FAILURE`. It must never be used as positive evidence.

### LEAN disagreement

The fast engine and LEAN produce materially different turnover and Sharpe values.

The disagreement remains in memory and can block promotion until the translation or accounting difference is resolved.

## Memory trust levels

```text
UNVERIFIED
VALIDATED
INDEPENDENTLY_VERIFIED
INVALIDATED
```

Only validated or independently verified memories can be used as positive research evidence.

Invalidated and failed memories remain retrievable because they help prevent repeated mistakes.

## Storage design

Canonical records live in PostgreSQL and S3.

Neo4j receives a derived graph projection for relationship queries such as:

```text
Which hypotheses repeatedly failed because of turnover?
Which experiments used the same paper and data family?
Which strategy branches disagreed with LEAN?
Which failed experiments inspired later successful hypotheses?
```

Elasticsearch indexes searchable text from research notes and failure summaries.

## Agent context

The model does not receive the entire ledger.

The memory retriever returns a compact set of relevant successes and failures with:

- reason for retrieval,
- trust level,
- experiment ID,
- failure class,
- key changed assumptions,
- evidence references.

This preserves the value of memory without flooding the model context.

## Training trajectories

Verified ledger events can also produce offline training trajectories.

A trajectory contains:

```text
state before action
action/tool chosen
tool arguments
observation
deterministic checks
semantic feedback
state after action
final research outcome
failure/success label
```

Failed trajectories are included when they teach the model what action or assumption should be avoided.

## Evaluation

Research memory is evaluated on:

- duplicate experiment reduction,
- correct retrieval of relevant failures,
- false reuse rate,
- bad-memory contamination rate,
- runtime saved,
- cost saved,
- improvement or regression in autonomous completion.

A memory feature is not accepted merely because the agent references previous work more often.

## RL and RLVR use of failed memory

The ledger is also the source for policy-learning data.

A verified failed experiment can become:

```text
negative state-action example
preference pair
terminal penalty
failure-conditioned recovery example
multi-step rollout transition
```

Only trajectories with complete lineage and known verifier status enter the trusted training corpus.

Training records preserve failure cases rather than filtering them out.
