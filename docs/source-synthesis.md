# Source-to-hybrid research

The synthesis command connects an investment idea to source ranking, model extraction,
independent direction review, a cited hybrid proposal and durable monthly execution.
The operator supplies a reviewed literature catalog and data/formation bindings; the
model selects the combination and weights. This initial path uses supplied source
packets rather than open-web discovery.

```powershell
uv run python scripts/prepare_synthesis_example.py --artifacts artifacts/synthesis --request synthesis-request.json
uv run python -m factorforge.orchestration.synthesis_command --request synthesis-request.json --artifacts artifacts/synthesis
```

Set `RDS_DSN` using the existing PostgreSQL setup and run Ollama with `llama3.1:8b` and
`qwen3:8b` already installed. The source extractor and independent reviewer retain
their fixed Llama profiles. A new fixed Qwen profile handles synthesis only. The original
example needs up to five model calls and one experiment, all under the brief's budget.

Use `--profile qwen-extraction-v1` with the preparation script to select the separately
versioned Qwen extraction candidate (`synthesis-research-request-v2`). This changes
extraction only; direction review still uses Llama. The original request/profile remains
the default and retains its original command identities and replay receipts.

The first live run on the frozen original two-source case retained 37 reachable artifacts
and settled both extraction attempts. Both drafts required a formation lag that the model
left unknown, so execution stopped at source admission. These original engineering inputs
are a development case; they do not measure published-factor accuracy.

On the same original inputs, Qwen extraction retained the correct formulas, directions
and known zero-month lags. Its formation-rule text included the source sentence's final
period; the reviewed label omitted it, so the exact-match gate retained both drafts for
review. `--source-literal-timing` prepares a separate development request whose reviewed
label includes that source period. This changes the curated binding and request identity;
it does not amend an existing result or relax the matching rule.

For the original example, `--reviewed-source-aliases` supplies three upfront reviewed
descriptions: the timing phrase, that phrase with a period, and the source's longer timing
sentence. Each alternative must occur in the exact supplied source, and model output must
match an enumerated alternative exactly. The full alias binding enters the strategy's
lineage. Unlisted wording still requires review; aliases do not modify typed execution
timing or other compiler checks. Existing requests without aliases retain their behavior.

Grade a saved command receipt without inference or database access:

```powershell
uv run python -m factorforge.evaluation.synthesis --receipt synthesis-receipt.json --artifacts artifacts/synthesis --output synthesis-scorecard.json
```

The grader verifies all reachable artifacts and checks the original case's formulas,
directions, compiled parents, weights, literal citations, initial capital, terminal NAV
and operation limits. Each scorecard retains the request identity so development variants
can be distinguished. These checks do not measure economic rationale or paper replication.

Each selected source is extracted into a typed draft. Only drafts with a supported,
agreeing source-only direction review enter synthesis. The synthesis model must select
at least two known parent IDs, cite a literal passage/page for each and supply positive
rational weights summing to one. It can abstain. Unknown sources, invented citations,
invalid weights and malformed output remain recorded without dispatching a hybrid.

The [hybrid compiler](hybrid-research.md) checks the parents' execution compatibility.
The model cannot rewrite formulas, data bindings, costs, funding rules or permissions.
Comparable raw score scales remain an explicit experimental assumption, and citation
membership does not prove the proposed economic rationale.

Every model attempt reserves before dispatch and retains its prompt, raw provider
evidence and typed outcome. Repeating an identical request recovers settled model and
backtest operations. A pending reservation requires reconciliation; it does not trigger
a second attempt. Local dollar cost remains unmeasured and keeps its reserved allowance.

The result links the full request, source/extraction stage, reviews, synthesis and hybrid
execution/report, including held outcomes. This is a separate typed result from the
existing `research-completion-v1` workflow. Automatic semantic memory insertion and
published-factor benchmark grading are not implied by command completion.
