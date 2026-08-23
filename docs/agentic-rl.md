# Agentic RL, RL Environments, and RLVR

## Role in FactorForge

FactorForge is agentic orchestration and harness engineering first. Agentic reinforcement learning is a post-MVP extension built on the verified trajectory, research-memory, and evaluation infrastructure.

The production harness remains authoritative even when a learned research policy is introduced.

The learned policy may propose the next research action. It cannot change:

- authorization,
- sandbox policy,
- point-in-time rules,
- accounting code,
- statistical validators,
- experiment budgets,
- lineage requirements,
- release gates,
- live-trading prohibition.

## Why FactorForge is a useful RL environment

Many agent tasks have weak rewards because success is subjective. FactorForge has a real executable environment with machine-verifiable feedback.

```text
research policy
      |
      v
structured action
      |
      v
research environment
      |
      +--> literature/search tools
      +--> sandbox experiment runner
      +--> Polars backtest engine
      +--> point-in-time validator
      +--> statistical validator
      +--> transaction-cost model
      +--> LEAN verifier
      +--> lineage validator
      +--> budget meter
      |
      v
observation + verifier reward
```

This makes it possible to study agentic RL without using live trading as the environment.

## Environment contract

The environment uses an explicit contract inspired by Gymnasium-style environments while preserving structured agent actions.

```python
aclass FactorForgeResearchEnv(Protocol):
    def reset(self, case_id: str, seed: int) -> Observation: ...
    def step(self, action: ResearchAction) -> StepResult: ...
```

`reset` restores a pinned research case, dataset references, budget, prior memory snapshot, and deterministic environment configuration.

`step` validates the action, executes allowed work, runs verifiers, records lineage, and returns the next observation.

## State

A research state can include:

```text
research question
retrieved paper IDs
active hypotheses
FactorSpec versions
completed experiments
failed experiments
validation results
remaining budget
current evidence
current research verdict
allowed next actions
```

A deterministic observation builder creates a compact policy observation rather than dumping the complete raw state into the model context.

## Action space

Actions are typed and bounded.

```text
SEARCH_LITERATURE
READ_PAPER
PROPOSE_HYPOTHESIS
REFINE_FACTOR_SPEC
RUN_EXPERIMENT
RUN_ROBUSTNESS_TEST
CHANGE_FORMATION_WINDOW
CHANGE_HOLDING_PERIOD
CHANGE_REBALANCE
REQUEST_LEAN_VERIFICATION
REJECT_BRANCH
PROMOTE_BRANCH
FINISH_RESEARCH
```

An action carries a schema. Free-form model text is not executed.

## Transition and objective

A trajectory is:

```text
tau = (s_0, a_0, r_0, s_1, a_1, r_1, ..., s_T)
```

with policy:

```text
pi_theta(a | s)
```

and the general objective:

```text
J(theta) =
E_tau[ sum_t gamma^t * r_t ]
```

The environment, reward version, policy version, and rollout dataset version are stored in lineage.

## Reward design

The reward must not be `+1 if Sharpe increases`.

That would create an incentive to overfit, p-hack, ignore costs, or exploit data leakage.

A decomposed research reward can be:

```text
R =
  w_evidence * Q_evidence
+ w_oos * Q_out_of_sample
+ w_robust * Q_robustness
+ w_repro * Q_reproducibility
+ w_progress * Q_research_progress
- w_llm * C_llm
- w_compute * C_compute
- w_repeat * P_redundancy
- w_complexity * P_complexity
```

Hard verifier failures override this soft utility.

Examples:

```text
lookahead leakage
sandbox violation
unauthorized tool
missing required lineage
invalid statistical method
budget violation
```

A transition with a hard violation receives the configured terminal failure reward and cannot become a successful trajectory because its backtest looked strong.

## RLVR

RLVR means reinforcement learning with verifiable rewards.

FactorForge uses deterministic and reference-based verifiers to create reward signals whenever possible.

Examples:

```text
FactorSpec schema validity
critical FactorSpec field correctness against gold cases
correct point-in-time ordering
no future information
successful deterministic accounting checks
required validator completion
LEAN agreement within declared tolerance
lineage completeness
sandbox policy compliance
budget compliance
research task terminal-state correctness
```

Semantic graders can contribute auxiliary information, but hard RLVR reward does not depend only on an LLM judge.

## Failed experiments as RL data

The failed-experiment ledger is central to the learning design.

```text
state:
residual momentum has high gross Sharpe and excessive monthly turnover

bad action:
rerun nearly identical configuration

better action:
test lower rebalance frequency

evidence:
prior experiment failed after transaction costs
```

A failed experiment can create:

- negative training examples,
- preference pairs,
- terminal penalties,
- failure-conditioned state transitions,
- examples of productive recovery actions.

The system learns from why an experiment failed, not only whether its return was positive.

## Training progression

### Stage 0: prompted deterministic baseline

Run the production LangGraph policy with no learned decision policy.

### Stage 1: supervised trajectory baseline

Train a narrow component on verified state-action examples.

Good first tasks:

- `FactorSpec` extraction,
- next-action classification/ranking,
- experiment-failure classification.

### Stage 2: preference learning

Construct preference pairs from verified trajectories:

```text
same or similar research state
preferred useful action
rejected redundant or invalid action
```

Use a TRL-supported preference method when it improves held-out behavior.

### Stage 3: RLVR on verifiable decisions

Train a policy using verifiable reward functions on tasks where the environment can grade the result.

A practical first RLVR task is structured next-action selection or FactorSpec generation because both have strong deterministic/reference-based validators.

A GRPO-style implementation is a candidate when the task formulation and current TRL support fit the experiment.

### Stage 4: multi-step agentic RL environment

Collect full environment rollouts:

```text
state
-> action
-> tool/experiment
-> verifier reward
-> next state
```

Train a research policy from the rollout corpus under a versioned algorithm.

The exact optimization method is selected after comparing simpler supervised and preference baselines.

### Stage 5: promotion comparison

Compare:

```text
prompted LangGraph policy
vs
supervised learned policy
vs
preference-trained policy
vs
RLVR policy
vs
multi-step agentic RL policy
```

The learned policy is promoted only if it improves held-out metrics without increasing hard execution-path violations.

## Training and evaluation separation

The 45-case public release benchmark is not training data.

Use separate:

```text
trajectory training set
development set
RL validation set
held-out transfer set
public 45-case release benchmark
```

The final public benchmark remains untouched until release evaluation.

## Reward hacking tests

The RL evaluation suite includes cases where a naive reward can be exploited:

- inflated Sharpe through lookahead leakage,
- gross return improvement with extreme turnover,
- skipping expensive validation,
- repeating cheap redundant actions to collect step reward,
- terminating early before required verification,
- producing a polished report without complete lineage,
- selecting actions that reduce cost by avoiding required evidence,
- abusing a permissive semantic judge.

A policy that exploits the reward fails even if its scalar reward is high.

## Observability

Every RL rollout records:

```text
environment version
policy version
reward version
state/observation hash
action
tool calls
verifier results
reward components
terminal reason
cost
trace IDs
```

LangSmith explains agent trajectories. OpenTelemetry traces distributed execution. MLflow records training/evaluation runs. DVC/S3 pins rollout datasets and artifacts.

## Infrastructure

Local RL work begins with small deterministic environments.

Later training can use:

- PyTorch,
- TRL,
- MLflow,
- DVC,
- EKS/EC2 worker classes,
- GPU nodes only when the workload justifies them.

The API is not coupled to the training runtime.

## Release posture

FactorForge does not assume reinforcement learning is superior.

The project demonstrates:

1. a reliable agentic environment,
2. verifiable rewards,
3. training from successful and failed trajectories,
4. controlled RLVR and agentic-RL experiments,
5. a promotion gate against the non-RL baseline.

If the learned policy loses, the production system keeps the stronger prompted/deterministic policy and preserves the failed RL experiment.
