# ADR-008: MCP for tools; A2A for cross-runtime agents

## Decision

Use MCP at stable tool boundaries and A2A only for a remote-agent interoperability demonstration. Core LangGraph subagents remain native and in-process where possible.

## Rationale

Tool and agent protocols solve different interoperability problems.

## Tradeoff

Protocol adapters add versioning and auth work.

## Switch condition

Expand A2A only when remote agents become independently deployed capabilities with a clear ownership or scaling reason.
