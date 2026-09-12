# LangSmith trace import

The exporter turns a verified research trajectory into SDK-validated LangSmith run
records: one research parent and one child per recorded operation. Stable IDs, recorded
reservation/settlement timestamps and parentage support inspection of retained research.
These records are explicitly tagged `retrospective`; they are not newly executed spans.

```powershell
uv run python tools/tracking/langsmith_export.py --request trajectory-request.json --artifacts artifacts/research --output langsmith-import.json
```

The default command writes only a local bundle. It invokes no model or backtest.
The bundle includes operation identity, type, sequence, status and provenance hash.
Source text, prompts, model response text and gold answers remain in the local artifact
store and are excluded from the hosted projection.

To upload, configure `LANGSMITH_API_KEY` and your LangSmith endpoint/workspace as
appropriate, then pass `--upload --project YOUR_PROJECT` with a fresh output file.
The command uses the real LangSmith client with batching disabled and flushes before
returning. Confirm project permissions, quota and imported run visibility in your
account after upload. The local serialization checks exercise stable IDs, parentage
and omission of source text through an owned loopback server.

See the official [custom instrumentation documentation](https://docs.langchain.com/langsmith/annotate-code)
for LangSmith run trees and tracing behavior.
