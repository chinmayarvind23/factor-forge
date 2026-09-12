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

## Execute a frozen development suite

`research_runner` dispatches the declared suite through the existing source-to-hybrid
worker, serially, with PostgreSQL run ownership and per-case budgets:

```powershell
uv run python -m factorforge.evaluation.research_runner --suite suite.json --artifacts artifacts/study --journal study.jsonl --max-reserved-microusd 10000000
```

Set `RDS_DSN` and the required local model services as for the synthesis command. The
reservation ceiling must cover the sum of all case brief budgets. It is authorized
capacity, not measured model spending. Every request and its complete artifact closure
are verified before any dispatch. Each batch creates new idempotency keys so previous
single-case runs cannot masquerade as fresh prospective execution.

The exclusive JSONL journal is flushed and synced before each dispatch. It retains
the suite reference, batch ID, case request, idempotency key, result reference when
available, terminal status and elapsed worker time. Exceptions retain their case in
the denominator; returned invalid evidence remains available for inspection and grading.
Held results remain held and do not become rubric passes.

The final `batch_recorded` row links a `ResearchSubmissions` artifact for the saved-result
evaluator. Reusing an existing journal path fails without dispatch. There is no automatic
retry or resume: after interruption, reconcile the recorded idempotency key against the
PostgreSQL run and operation ledgers. Do not start another batch as a substitute for
reconciling uncertain work. A journal storage error stops subsequent dispatches.

The runner enables prospective development execution but does not supply the frozen
45-case release inventory, broader task rubrics or proof of release autonomy.
