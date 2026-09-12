# Security and operation boundaries

Models propose research content. Deterministic software enforces authorization, source
admission, budgets and execution constraints.

## Identity and permissions

Local API mode binds to a trusted loopback workflow. Cognito mode validates access tokens
and application capabilities. Owner-scoped reads and operation checks prevent a model or
client from gaining access merely by naming an object or tool.

Use dedicated database roles and artifact roots. Keep credentials out of source documents,
model prompts, tool output and logs. Do not expose database administration, Docker sockets
or operator-only endpoints through the demo.

## Untrusted content and code

Paper text, retrieved metadata, model output and research memory are data. They do not
change system policy. Strict structured contracts validate supported fields before those
values reach execution code.

Generated-code execution uses the [sandbox](../infra/sandbox/README.md): non-root processes,
restricted capabilities, bounded resources, declared read-only inputs and network restrictions.
Review the actual runtime configuration before using another host. A timeout or rejected
output remains a terminal record; it must not be replaced with a successful-looking value.

## Data and replay

Verify content identity when loading artifacts. Preserve the declared known-at timestamps,
borrowing grants, input rights and action terms. Uncertain external operations require
reconciliation before retry. Kafka consumer offsets follow durable journal writes.

Optional query services are read-only views over operator-selected saved material. Keep
service authentication, transport protection and storage access aligned with the deployment.
Run the dependency checks described in [development](development.md) before changing images
or package locks; retain the DVC tooling's advisory gate.
