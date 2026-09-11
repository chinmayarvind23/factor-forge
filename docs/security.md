# Security

## Objective

FactorForge lets models propose and execute research code. Security is enforced by software and runtime boundaries, not by asking the model to behave.

## Authentication

AWS Cognito provides user authentication. FastAPI validates OIDC/JWT tokens and maps identity into application roles and capabilities.

## Authorization

Capabilities are checked before tools are exposed to an agent and again when a tool executes. A model cannot gain a capability by naming an unregistered tool.

## Workload identity

Cloud workers use short-lived workload identity and narrow IAM permissions. Experiment jobs can read approved dataset/artifact prefixes, write their run-scoped output prefix, emit telemetry, and report results. They cannot access unrelated production secrets.

## Secrets

Use AWS Secrets Manager or equivalent deployment secret storage.

Never commit secrets, pass brokerage credentials to the system, include API keys in prompts, or log raw authorization headers.

## Sandbox

Generated code is untrusted.

Required controls:

- non-root,
- no privileged container,
- no host mounts beyond explicit read-only inputs,
- no Docker socket,
- default-deny network,
- CPU/memory/PID quotas,
- deadline,
- output-size limit,
- filesystem quota,
- restricted Linux capabilities,
- kill path.

## Prompt injection

Paper text, web content, memory entries, and peer-agent messages are data and may contain malicious instructions.

Defenses:

- provenance-tag external content,
- never concatenate external text into privileged policy,
- fixed tool capability policy outside the model,
- validate tool calls,
- separate retrieval permission from execution permission,
- allowlist network/data sources,
- treat instructions found in retrieved content as untrusted text.

## Data poisoning

Record source, hash content, version snapshots, flag conflicts, and preserve disagreements across sources.

## Model-generated code

Code passes static policy checks, dependency allowlist checks, sandbox policy, and timeout/resource contracts. Static scanning is defense in depth; the sandbox is the actual boundary.

## Human approval

Approval is required for high-cost cloud research beyond configured budget, shared infrastructure mutation, destructive artifact deletion, and credential/permission changes.

Live trading is unavailable.

## Logging

Redact secrets and sensitive fields before logs/traces leave the process. Store prompt/response text only when allowed by trace policy.

## Supply chain

Current CI audits locked application Python dependencies and the web package. DVC has a separate
locked environment and a required audit before execution. Its diskcache dependency has an
unresolved advisory, so the [complete release gate](../tools/dvc/README.md) remains blocked.
Isolation is not remediation. CodeQL/Semgrep, container and Terraform checks, and benchmark
image pinning remain planned for the corresponding implementation stages.

## Security testing

Implemented adversarial checks cover identity/capability boundaries, malformed requests,
checkpoint failures, local path escape, corrupt artifacts, conflicting point-in-time history
and tampered fixture bundles. Execution sandboxes and their exfiltration, fork-bomb, OOM and
process-control tests remain planned. Paper prompt-injection and inter-agent tests will be
added with those model/tool paths; their presence is not implied by this design document.
