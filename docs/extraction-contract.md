# Source extraction contract

`SourceExtraction` records what a paper passage supports. It does not authorize execution, establish investability, or replace the later validated `FactorSpec`.

Every field is required in the JSON output, including nullable fields. A missing quantity is `null`; a known zero reporting lag is `0`. `lookback_months` denotes a fixed trailing return-ranking window. An annual accounting window belongs in `formation_rule`. `holding_months` denotes the selected cohort or portfolio reconstitution horizon, not an instruction to force every security out after that duration. `formation_lag_months` is a fixed measurement-to-holding gap; calendar-based rules that have no fixed gap use `null` and describe the timing in `formation_rule`.

`required_inputs` names inputs to the sorting signal. Execution, universe, market-cap weighting, and reference-return requirements will be represented in the downstream strategy contract. `source_pages` uses one-based physical PDF page numbers from the supplied passage set. Successful parsing does not verify that a cited page exists or supports the claim; the evaluation and source-binding layer must do that separately.

An `extracted` response carries source pages and no refusal fields. Individual unknown strategy fields may remain null. A `refused` response requires a reason and one of `safety`, `input_mismatch`, or `insufficient_information`, and cannot also assert a strategy. Refusals and malformed responses must remain in evaluation denominators.

The parser accepts one UTF-8 JSON object of at most 32 KiB and 16 container levels. It rejects duplicate keys, nonfinite numbers, wrong types, unexpected fields, duplicate input names or page numbers, and contradictory states. It performs no fence stripping, substring extraction, or output repair. Provider delivery and extraction validity are separate outcomes; neither alone establishes extraction accuracy.

The one-shot source extractor accepts a selected strategy and at most 16 physical page references, totaling at most 256 KiB. It verifies the saved bytes, decodes UTF-8, and collapses whitespace using the versioned `utf8-whitespace-collapse-v1` transform. Full raw page artifacts remain available. Page order is ascending by physical page number. No page is silently dropped to fit a request.

The fixed `source-extraction-v1` prompt provides field conventions and an arithmetic vocabulary, and treats page text as untrusted data. It receives the selected-strategy label and source pages, not gold answers or numerical grading examples. This is extraction conditioned on an explicit strategy selection, not independent strategy discovery. Formula syntax and numerical checks use the [bounded formula language](formula-language.md).

Each attempt retains the source packet, prepared prompt/schema, verified provider record when admitted, parsed observation when valid, and terminal extraction record. Outcomes are `extracted`, `refused`, `invalid`, `provider_failed`, or `input_rejected`. Missing artifact evidence prevents success; unexpected provider or storage errors propagate rather than being relabeled as model mistakes. The default local profile permits a 24 KiB complete wire request and 2,048 output tokens in a 32,768-token context, with no retry or repair. Oversized input retains an admission-failure record.

Citations outside the supplied page set make the observation invalid. Subset membership alone does not establish that the source supports each asserted field. The later evaluation must keep this limitation separate from numerical and structural correctness.

## Critical-field development grader

The `critical_field_pilot` grader evaluates nine named fields: formula, required signal inputs,
long/short direction, bucket count, weighting, return lookback, holding horizon, rebalance frequency,
and fixed formation lag. Input sets are order-independent; the remaining structural values use
exact equality with the declared null conventions. A formula must use the declared input names
and match all three frozen numerical examples exactly under the bounded interpreter. This admits
some algebraic rearrangements, but finite examples do not prove symbolic equivalence.

Gold validates its own formula against the examples before scoring. Every frozen case requires an
attempt entry; missing, duplicate or extra case identifiers stop evaluation. Refused, malformed,
provider-failed and input-rejected attempts receive zero of nine field matches and remain in the
denominator. Reports expose per-field decisions, total field accuracy, and the fraction of cases
matching all nine fields. Reloaded reports validate their counts against their per-case rows.

Formation prose is retained for review and is not machine-graded. Page membership is checked,
not passage entailment. The runner must bind the actual source packet to the gold paper identity,
PDF hash and selected pages before invoking a provider; the arithmetic grader alone cannot prove
where an observation came from. This development metric is not full executable `FactorSpec`
accuracy, empirical factor replication, or the 15-paper release benchmark.
