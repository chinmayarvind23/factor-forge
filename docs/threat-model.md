# Threat Model

## Assets

- research data,
- proprietary/licensed snapshots,
- user identity,
- API/cloud credentials,
- generated code,
- benchmark integrity,
- research lineage,
- experiment budget,
- infrastructure availability.

## Trust boundaries

```text
browser
  |
  | untrusted input
  v
public API
  |
  | authenticated application boundary
  v
orchestrator
  |
  +--> external literature/data providers
  +--> model providers
  +--> search/memory stores
  +--> queue
          |
          | untrusted generated code boundary
          v
       experiment sandbox
```

## Confused deputy

An attacker places an instruction in a paper or prompt that asks the agent to use stronger credentials.

Control: tool capability checks and authorization outside the model.

## Prompt injection

A retrieved source attempts to rewrite system behavior.

Control: provenance-tagged data, fixed policy, typed tools, no direct execution from retrieved text.

## Sandbox escape

Generated code attempts host or network access.

Control: container/Kubernetes security policy, no host socket, no privileges, default-deny network, resource limits.

## Denial of wallet

A prompt causes endless model/tool calls.

Control: token, dollar, iteration, wall-clock, and experiment budgets in code.

## Denial of compute

Generated code loops, forks, or allocates memory.

Control: CPU, memory, PID, storage, deadline, and job quotas.

## Data leakage

A model receives data outside the run's permitted dataset.

Control: run-scoped object prefixes, application authorization, workload identity.

## Research integrity attack

A malicious source or memory record biases factor extraction.

Control: stable provenance, conflict surfacing, multi-source evidence, benchmark gold labels.

## Trajectory poisoning

A failed or malicious prior run influences future runs as trusted memory.

Control: memory entries carry verification state; unverified memory is not promoted into trusted research memory.

## Inter-agent injection

A remote A2A agent returns operational instructions.

Control: parse the response into a typed data contract and never grant direct privileged execution.

## Irreversible actions

FactorForge intentionally removes live trading. Infrastructure deletion and high-cost runs require explicit human approval.
