# Source observations to monthly strategy drafts

`factors/source_strategy.py` compiles a `SourceExtraction` against an explicit
`RawStrategySpec` environment. The caller supplies reviewed input names, concepts,
units, historical membership, calendar, market data, evaluation window, fees and
funding policies. The template is a convenient reuse of the existing complete
execution contract; its formula and portfolio direction are replaced by source
choices. This avoids introducing a second independent data-binding schema.

The compiler requires exact input-name agreement and a source formation-rule
string matching the caller's reviewed rule. That review asserts the rule means
the template's monthly last-session close convention. Text equality does not
establish semantic correctness. The caller must obtain this mapping during source
onboarding; copying an arbitrary model string into the review field is insufficient.

Formula, direction, bucket count, lag and lookback come from the observation.
The current monthly profile supports equal weights and one-month holdings.
Unknown or unsupported choices produce a retained request and reason codes.
A null lookback stays null; historical formula calls must independently satisfy
the raw contract's input-unit and history requirements. Input names are never
renamed to fit available data, and source-page observations stay in the request.

The resulting factor ID derives from the complete request hash. Full raw-contract
validation checks formula closure, dimensions, allocation and source roles. A
draft retains the environment's source references. The coordinator must publish
the complete draft together with upstream extraction evidence before execution;
this pure compiler neither reads source artifacts nor attests extraction accuracy.
Actual monthly admission still verifies data bytes and rights. The existing
profile accepts original fixtures; published historical data support is separate.

Validation covers executable compilation against the original monthly oracle,
source direction changes, unknown fields, input mismatch, unsupported timing and
weighting, invalid formulas, historical formulas and source refusal. The compiled
original fixture reaches terminal NAV 1057.98 through the actual monthly engine.
