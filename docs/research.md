# Research operator

Use a dedicated PostgreSQL database, an Ollama server and a persistent artifact directory.
Install the core environment with `uv sync --locked`. Set `RDS_DSN` in the process environment;
no environment file is loaded implicitly. The operator uses a fixed local identity.

## Prepare and run

```powershell
ollama pull llama3.1:8b
uv run python infra/research/prepare_original.py --artifacts artifacts/research-original --request artifacts/research-original/request.json
uv run factorforge-research --request artifacts/research-original/request.json --artifacts artifacts/research-original --workflow
```

Preparation creates a fresh request from the authored example source. Preserve that file:
its brief, plan and evaluation clock identify the workflow. The full workflow handles research,
report publication and memory with PostgreSQL checkpoints. Inspect the retained decision
rather than assuming every compiled candidate is eligible for execution.

Use `--direction-review` or `--direction-revision` when preparing a new request to include
source-cited direction review or bounded revision. Those choices become part of the saved
plan and its budget. Use a new output path instead of overwriting a request.

## Resume and inspect

Repeat the workflow command with the same request and artifact directory. Existing receipts
and checkpoints determine which stages need work. Pending provider operations are reconciled
before another call is permitted.

```powershell
uv run factorforge-research --artifacts artifacts/research-original --memory-query "momentum"
```

Memory returns references to saved decisions. Follow their source artifacts to inspect the
model interpretation, strategy and execution record. Keep database backups and artifact
backups together.

## Models and integrations

Provider profiles support the named local Ollama models, including Llama and Qwen. Select
provider options through the command's help and the typed request plan. Optional
[Deep Agents planning](../tools/planning/README.md) converts an idea into a bounded proposal.
For multiple papers, use the [synthesis command](../src/factorforge/orchestration/synthesis_command.py)
with reviewed source and strategy bindings.

[Sources and data](data.md) describes how to prepare your own input. The application
[API](../src/factorforge/api/app.py) handles authenticated or loopback-local requests;
the operator command is the entry point for the complete research workflow.
