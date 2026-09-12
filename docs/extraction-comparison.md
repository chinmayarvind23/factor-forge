# Published-paper extraction comparison

The comparison runner evaluates a named local model against an existing frozen paper
development suite. It preserves the source packet, nine-field gold case, exact wire
request, installed source, environment, provider response and grade for each attempt.
Gold remains outside the model request. Every case receives one attempt.

```powershell
python scripts/run_extraction_comparison.py --baseline PATH_TO_PREPARED_BASELINE --output NEW_OUTPUT_DIRECTORY --model qwen3:8b
```

The baseline directory contains `prepared-gold-v1.json`, an `objects` artifact store,
and `case-inputs/PAPER_ID-packet.json` files. Each prepared-gold case row identifies a
`GoldCase` artifact. Use source text you are permitted to retain locally; the public
repository does not redistribute the private paper corpus.

Before inference, the runner writes all source packets, gold cases and expected wire
requests, then a freeze manifest. A fresh output directory is mandatory. Each completed
case is saved immediately; a process error leaves earlier evidence intact and does not
automatically retry. The final report includes every attempted case and a verified
bundle links the report, trials, freeze, runner and local OpenTelemetry spans.

For a single case, the existing CLI also accepts `--model qwen3:8b`:

```powershell
python -m factorforge.evaluation.source_trial --packet packet.json --gold gold.json --expected-request wire-reference.json --output EXISTING_OBJECT_STORE --model qwen3:8b
```

The expected request must have been frozen for that exact model. A Llama request cannot
authorize a Qwen call. Omitting `--model` preserves the original Llama profile.

Scores use the [existing extraction contract](extraction-contract.md). This is a
development comparison with fixed critical-field checks, not the full 15-paper
FactorSpec benchmark. Formation-rule prose and citation entailment require separate
review. No production model promotion follows automatically from the comparison.

The retained three-paper comparison used identical messages, schema, context/output
settings and source pages to the original run. The wire differences were the model
name and Qwen's explicit `think=false`. Llama matched 11/27 critical fields; Qwen
matched 8/27. Both scored 0/3 on all-nine-fields case accuracy. The Qwen run retained
one response-timeout outcome and two parsed extractions, with all three cases kept
in the denominator. Its evidence bundle verifies 70 reachable objects. These results
guide further extraction work; model defaults remain unchanged.

## Evidence-first development profile

Add `--style evidence-first-v1` to either command to evaluate the experimental
`source-evidence-first-v1` prompt. It asks for short literal quotations before a nested
strategy observation. Each quotation lists the fields it supports and its physical
page. The parser checks page membership, whitespace-normalized quote membership and
coverage of all non-null strategy fields and nonempty required inputs. Unsupported
fields must remain null or empty. Invalid evidence makes the whole observation invalid;
the raw answer remains in provider artifacts.

This check establishes literal source membership and declared field coverage, not
semantic entailment of a formula or investment claim. The existing nine-field grader
still determines development accuracy. Neither the prompt nor its parser sees gold.
The original profile remains the default. The new schema omits descriptive titles and
descriptions to fit the existing request bound; types, enums, required fields and
validation bounds remain intact. Original source pages are neither truncated nor edited.

The first live evidence-first comparison retained three response-timeout outcomes
under the unchanged 120-second response limit (0/27 graded fields). Its 67-object
evidence closure verifies. The profile remains experimental and is not the default.
