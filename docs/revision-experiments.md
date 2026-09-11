# Quote-first revision experiments

`infra/research/probe_revision.py` runs one explicitly requested local-model probe
from a saved `DirectionRevisionRequest` and its staged artifacts. It is separate
from production scheduling and cannot change an earlier run's budget or evidence.
The exclusive JSONL receipt records a started request before delivery and a result
reference afterward. Reusing the output path fails before another model call.

```powershell
uv run python infra/research/probe_revision.py --request conflict.json --artifacts artifacts/revision-probe --output artifacts/revision-probe/receipt.jsonl
```

The `quote-first-revision-probe-v1` profile asks the model to copy `citation` before
choosing direction. Citation sorts before direction in the provider's canonical
JSON; JSON Schema does not guarantee generation order. The unchanged strict parser
and exact quote-membership check then validate the response. Legacy `quote` fields
or both field names are rejected. The public observation still uses the existing
`DirectionObservation` shape after validation.

Add `--source-only` and a distinct output path for
`source-only-quote-first-revision-probe-v1`. This variant omits both prior model
judgments from the prompt but retains them in its evidence record. Both variants
use the same bounded local provider with a 180-second deadline allowance and no
inferred dollar charge.

On the frozen original-source conflict, the contextual variant returned a valid
source passage with the reversed direction. The source-only variant returned the
correct direction but cited only the strategy title. Neither variant was promoted.
All 28 artifacts reachable from the two probe receipts verified by size and SHA-256.
These are two development observations on one original source, with manual
assessment of direction and quote support; they are not release accuracy estimates.

Production review/revision prompts, command identities and scheduling policies remain
unchanged. A supported observation still means valid syntax and source membership,
not semantic entailment. Further model work needs broader frozen examples and an
explicit assessment of whether the cited text supports the claimed direction.
