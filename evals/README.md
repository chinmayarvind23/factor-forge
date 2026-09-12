# FactorForge evaluation layers

The current custom offline slice freezes ten original direction examples in
`cases/custom/direction-v1.json`. They cover both directions, quintile interpretation,
signed scores, missing direction, a missing short leg, strategy selection, an embedded
instruction, contradictory rules and negation. Case IDs are neutral. Gold labels and
support anchors are evaluator-only fields; runtime requests contain selected strategy
and source pages only.

The rubric reports direction correctness, cited support and their conjunction. On an
explicit-direction case, the quote must occur on the source page and contain all
predeclared support anchors. On an ambiguous case, an actual uncertain observation
with no guessed direction/quote is required. Provider failure does not earn abstention
credit. Anchor inclusion is a conservative original-case rubric, not general semantic
entailment or published-factor accuracy.

```powershell
uv run python evals/runner.py --artifacts artifacts/direction-eval --output artifacts/direction-eval/run.jsonl
uv run python evals/ci_gate.py --baseline baseline.json --candidate candidate.json
```

The runner uses the fixed source-only reviewer, existing local model profile and one
600-second provider allowance. It creates an exclusive journal before inference and
retains each case grade and provider evidence before advancing. Reusing the journal
path refuses another run. Model outcomes remain separate from execution-path tests.
The comparator requires the same suite reference and ordered case IDs and rejects a
relative pass-count regression of at least five percent. It consumes saved evaluation
JSON, regrades every observation against the frozen source labels, and starts no model.
Unit CI exercises the grader and comparator. Supply explicit baseline and candidate
artifacts to apply the model-output gate.

The optional `--profile complete-evidence-v1` runs a fixed development prompt that
explicitly requires both trading legs, resolves ranking definitions in the cited excerpt,
and requests uncertainty for incomplete or conflicting instructions. It uses the same
model, schema, parser and frozen cases as the baseline. The journal records its profile
and prompt digest; every case retains the actual request. This profile is an experiment
and does not change the production reviewer. Use a new output journal for its single
comparison run. Improvement on these exposed development cases needs separate held-out
validation before any broader accuracy claim.

`--profile qwen3-baseline-v1` compares the installed `qwen3:8b` model using the original
baseline prompt, unchanged cases, schema and limits. Its wire request explicitly sets
`think: false` using [Ollama's thinking control](https://docs.ollama.com/capabilities/thinking).
Actual model digests and wire requests remain in provider evidence. The runner does not
download models. Production workers continue to select `llama3.1:8b`. The evaluation's
prompt digest is intentionally identical to the baseline; model identity is recorded
in each provider capture and the journal profile identifies the comparison.

`--profile qwen3-coherent-v1` keeps the Qwen model and baseline prompt but generates a
`judgment` envelope with two disjoint schema branches: cited direction with null
uncertainty, or null direction/citation/page with an uncertainty explanation. Pydantic
validates the envelope before passing its unchanged judgment to the existing parser.
This experiment constrains combinations during generation; it does not repair saved
responses, change gold labels or relax citation requirements. Schemas are derived from
Pydantic with references inlined for the local Ollama provider.

`cases/custom/direction-validation-v1.json` freezes eight additional original examples
after candidate selection and before either validation run. They cover position signs,
accrual ordering, reverse decile numbering, explicit rule replacement, strategy selection,
long-only and short-only portfolios, and an unknown regime. These are authored validation
examples, not published-paper evidence or statistically independent authorship.
Run the production `baseline` and frozen `qwen3-coherent-v1` once each with this file
through `--cases`. Predeclared selection requires at least 7/8 joint passes, all three
uncertain cases correct, and no regression against the baseline on the same suite.
An accepted validation result is necessary for a versioned production-profile change;
scheduler integration checks remain a separate requirement.

See [development](../docs/development.md) for local checks and
[research](../docs/research.md) for the operator workflow.
