# Demo Plan

## Goal

Show research judgment and failure handling, not a chat window.

## Main screen

Expose:

```text
Research idea
Current state
Remaining experiment / cost budget
Literature evidence
Hypothesis queue
Active experiments
Validation results
LEAN verification
Research memory links
Final verdict
Reproduction bundle
```

## Sequence

1. Start with a vague idea such as: `Does residual momentum survive sector neutralization and realistic turnover costs?`
2. Show the normalized brief and typed hypotheses.
3. Show literature evidence and source-backed FactorSpec.
4. Show dataset version, timing rules, baseline, metrics, cost model, windows, and experiment budget.
5. Show sandboxed execution with resource policy and generated-code hash.
6. Show walk-forward, transaction costs, HAC t-stat, turnover, drawdown, and failure criteria.
7. Show LEAN agreement or disagreement.
8. Show the memory graph linking paper, hypothesis, experiment, and result.
9. Run an adversarial generated script that attempts network access and show `SECURITY_BLOCK` with preserved trace.
10. Show the benchmark table and one reproducible case bundle.

Record a short screen capture and stable screenshots/sample outputs so the project remains understandable even if the live deployment is offline.

## Agentic RL demonstration

After the core product demo, show one held-out research state under:

```text
prompted baseline
supervised trajectory policy
RLVR policy
```

Display the selected next action, verifier reward breakdown, whether the action advanced research, redundant/invalid action rate, cost/latency, and final hard-path status.

Include a failed-experiment memory item that causes the learned policy to avoid repeating a known bad experiment.
