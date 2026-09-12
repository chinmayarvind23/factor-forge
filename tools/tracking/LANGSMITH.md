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
returning. Hosted project creation, quota, readback and replay behavior still require
verification against your account. No hosted upload has been claimed or performed in
the current development environment because credentials are absent.

The real retained five-operation run produced six SDK-validated records. Tests verify
stable IDs, parentage and omission of source text, plus actual SDK HTTP serialization
against an owned loopback server. That transport contract test is not a hosted service
acceptance test. These retrospective imports do not contribute to the target count of
unique live agent/tool spans.

See the official [custom instrumentation documentation](https://docs.langchain.com/langsmith/annotate-code)
for LangSmith run trees and tracing behavior.
