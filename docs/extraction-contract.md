# Source extraction contract

`SourceExtraction` records what a paper passage supports. It does not authorize execution, establish investability, or replace the later validated `FactorSpec`.

Every field is required in the JSON output, including nullable fields. A missing quantity is `null`; a known zero reporting lag is `0`. `lookback_months` denotes a fixed trailing return-ranking window. An annual accounting window belongs in `formation_rule`. `holding_months` denotes the selected cohort or portfolio reconstitution horizon, not an instruction to force every security out after that duration. `formation_lag_months` is a fixed measurement-to-holding gap; calendar-based rules that have no fixed gap use `null` and describe the timing in `formation_rule`.

`required_inputs` names inputs to the sorting signal. Execution, universe, market-cap weighting, and reference-return requirements will be represented in the downstream strategy contract. `source_pages` uses one-based physical PDF page numbers from the supplied passage set. Successful parsing does not verify that a cited page exists or supports the claim; the evaluation and source-binding layer must do that separately.

An `extracted` response carries source pages and no refusal fields. Individual unknown strategy fields may remain null. A `refused` response requires a reason and one of `safety`, `input_mismatch`, or `insufficient_information`, and cannot also assert a strategy. Refusals and malformed responses must remain in evaluation denominators.

The parser accepts one UTF-8 JSON object of at most 32 KiB and 16 container levels. It rejects duplicate keys, nonfinite numbers, wrong types, unexpected fields, duplicate input names or page numbers, and contradictory states. It performs no fence stripping, substring extraction, or output repair. Provider delivery and extraction validity are separate outcomes; neither alone establishes extraction accuracy.
