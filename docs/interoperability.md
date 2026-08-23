# Interoperability

## Principle

Protocols are used where they reduce coupling across real boundaries. They are not inserted into in-process code that already has a simpler function call.

## MCP

MCP is the tool interoperability layer.

Candidate literature tools/resources:

```text
search_papers
get_paper_metadata
get_citation_neighbors
```

Candidate data-catalog tools:

```text
list_dataset_versions
get_dataset_manifest
resolve_symbol_history
```

Candidate experiment tools:

```text
get_experiment
list_related_experiments
get_mlflow_run
```

The LangGraph/Deep Agents runtime can use native tools internally while exposing or consuming MCP at stable integration boundaries.

## A2A

A2A is used for agent-to-agent interoperability, not ordinary tool calls.

```text
FactorForge LangGraph researcher
        |
       A2A
        |
remote Google ADK research critic
        |
     MCP tools
        |
approved literature/data services
```

The remote agent receives a bounded critique task and returns a typed result. It does not inherit FactorForge orchestrator authority.

## Google ADK

Google ADK is selected for the cross-framework A2A demonstration. The main production-shaped deployment remains AWS-based.

## Security

Remote-agent messages are untrusted data. Validate agent identity, task type, response schema, allowed references, size limits, timeout, and trace correlation.

A remote response cannot directly launch an experiment or mutate infrastructure.

## gRPC

gRPC serves the internal LEAN verification boundary because the interface is structured, internal, and benefits from generated contracts.

## GraphQL

GraphQL is an optional read-oriented exploration API for connected research/eval entities. State changes remain REST commands.

## Protocol benchmark

Evaluate schema conformance, error behavior, auth propagation, latency, trace propagation, version negotiation, and failure isolation. Protocol use itself is not improving research quality.
