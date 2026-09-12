# Retained research trajectories

The trajectory exporter turns a saved research result or budget into one JSONL row per
recorded operation. It reads verified artifacts and invokes no model, backtest or network
service. Pending operations and settled operations without a captured model record remain
visible in the inventory.

Each model attempt retains its exact system/user messages, response schema, parseable
assistant text, raw request/response references, model profile and identity, token counts,
wall time and billing scope. Worker decision status stays separate from provider delivery
status. Malformed responses keep their raw reference without an invented assistant message.
Only the worker's own result edge identifies its model attempt: earlier calls referenced by
its inputs are not counted again. Non-model operations retain their result references.

Create a request using a saved `research-completion-v1`, `synthesis-research-result-v1`,
`hybrid-experiment-result-v1` or `research-budget-v1` reference:

```json
{
  "schema_version": "trajectory-request-v1",
  "source": {"sha256": "<saved result SHA-256>", "size_bytes": 1234, "media_type": "application/json"},
  "partition": "development"
}
```

Use the exact saved reference, including its byte size. `partition` is required and accepts
`development` or `evaluation`; it is a caller declaration, not proof of dataset isolation.

```powershell
uv run python -m factorforge.lineage.trajectories --request trajectory-request.json --artifacts artifacts/research --output research-trajectories.jsonl
```

The command refuses to overwrite the output file. It also publishes a typed manifest with
operation, model-attempt, pending and uncaptured-attempt counts. The manifest links both
the JSONL and the original result, preserving the source artifact closure.

All rows are **unreviewed for training**. Parsing, provider success and an agent's own
decision are not correctness rewards. This is trajectory capture, not SFT, RL training or
a promotion decision. Evaluation data must remain separate from any future training corpus.
Export remains local; it does not upload source material or grant training rights.

Four saved live development runs exported **12 recorded model operations** with complete
provider-record coverage and no pending operations. Repeated exports produced identical
artifacts with model dispatch disabled. The corpus includes extraction outcomes, independent
reviews and a synthesis abstention. These counts describe that development corpus, not the
45-case release benchmark or 1,200-span observability target.
