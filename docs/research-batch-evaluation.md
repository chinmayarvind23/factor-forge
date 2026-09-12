# Saved research batch evaluation

The batch evaluator regrades retained source-to-hybrid attempts against the existing
`synthesis-original-v1` rubric. It reports each case's input identity, result identity,
evidence status, checks and criterion outcome. Missing and invalid cases stay in the
total. This is a development evaluator; it does not count release autonomy or published
factor reproduction.

A `ResearchSuite` declares unique case IDs and request artifact references. A separate
`ResearchSubmissions` manifest identifies the canonical suite artifact and supplies
available result references. Missing submissions are allowed; duplicate IDs, duplicate
inputs, repeated result objects and unknown cases are rejected. Keep the suite frozen
before a prospective comparison. A retrospectively assembled inventory must be labelled
as such in its study record.

```powershell
uv run python -m factorforge.evaluation.research_batch --suite suite.json --submissions submissions.json --artifacts artifacts/study --output scorecard.json
```

The evaluator verifies each result's reachable artifacts into a read-only snapshot,
binds the result to the declared request, checks budget/run and canonical brief
identities, and recomputes the original rubric. It starts no model, database connection
or experiment. The output path must be new. Identical inputs produce identical JSON
values, making saved-result comparison reproducible.

The suite digest identifies canonical contract bytes, not the whitespace of a JSON
file. Construct manifests with `ResearchSuite`, `ResearchCase`, `ResearchSubmissions`
and `Submission` from `factorforge.evaluation.research_batch`. Publishing the suite
with `factorforge.factors.hybrid.publish` returns the required artifact reference.

A verified evidence status means the closure and input/budget bindings passed. It does
not mean the research criteria passed. Likewise, a criterion pass would not establish
absence of human intervention or complete release execution-path coverage. The broader
45-case benchmark still needs frozen research cases, appropriate per-case rubrics and
runtime execution-path evidence. This adapter accepts only the existing original
synthesis rubric; other research tasks need their own graders.
