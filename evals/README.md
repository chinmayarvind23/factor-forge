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
Unit CI exercises the grader and comparator; automated model
score gating awaits a reviewed baseline artifact distribution path.

Layer status:

- Static release benchmarks: the planned 15 reproduction / 15 synthesis / 15 adversarial
  cases remain a separate release deliverable; these original examples do not replace them.
- Custom offline: direction/citation rubric and frozen cases implemented. Existing real
  PostgreSQL tests verify dispatch, replay, amendments, budget effects and reports. A
  calibrated source-grounded LLM judge and a general optimizer loop remain future work.
- Online: retained operator replays and provider cost/latency records exist. OTel GenAI
  spans, guardrail alerts and production evaluation aggregation remain future work.

The first live run completed all ten cases using `llama3.1:8b`: seven met the direction
criterion, six met cited support, and six met both. All 64 reachable artifacts verified.
The suite was frozen in `33e4e86` before inference; labels and anchors remain unchanged.
See [recorded results](../docs/results.md#original-direction-development-baseline).
Complete provider evidence is retained outside the repository by the operator.

The optional `--profile complete-evidence-v1` runs a fixed development prompt that
explicitly requires both trading legs, resolves ranking definitions in the cited excerpt,
and requests uncertainty for incomplete or conflicting instructions. It uses the same
model, schema, parser and frozen cases as the baseline. The journal records its profile
and prompt digest; every case retains the actual request. This profile is an experiment
and does not change the production reviewer. Use a new output journal for its single
comparison run. Improvement on these exposed development cases needs separate held-out
validation before any broader accuracy claim.

What to read next: [observability](../docs/observability.md) for the span substrate,
[failure modes](../docs/failure-modes.md) for coverage, and
[research reports](../docs/research-reports.md) for evidence-based execution summaries.
