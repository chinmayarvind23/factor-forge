# Factor contracts and hypothesis admission

`FactorSpec` describes a complete declared strategy. A nullable `SourceExtraction` is evidence
for that contract, not a substitute for it. `Hypothesis` can retain an incomplete draft and its
unresolved questions; those drafts remain blocked in the planning queue.

The first supported contract is an equity cross-sectional long-short strategy. Every timing,
data, portfolio and cost choice is required. It binds exact manifest and table artifacts,
source evidence, units, publication and revision fields, historical membership, calendar,
signal formula, return series, benchmark and risk-free series. No field supplies an implicit
zero cost, currency conversion, reporting lag or missing-return repair.

Formation occurs at session close and trading at a later session open. Rebalancing is monthly
or annually at June's last session. Holding periods align with the rebalance interval; longer
holdings require equal allocation across active vintages. The initial portfolio uses all
eligible securities for breakpoints, stable security IDs for ties, and explicit equal or
value weighting. Long and short sleeves each have unit exposure, giving target gross
exposure two relative to pre-trade NAV. Costs reduce NAV separately, so realized
post-cost gross exposure can exceed two. Short proceeds are segregated and cash earns zero.
An engine must enforce these policies, funding and portfolio accounting before execution can pass.
The [session calendar](session-calendar.md) binds canonical schedule bytes and rejects versions
that were unavailable at formation; calendar completeness remains an explicit source assertion.

`factor-spec-v2` requires `balanced_contiguous_low_remainder` bucket allocation and
`pre_trade_nav` sizing explicitly. After missing-signal exclusions, sort ascending by signal
then stable security ID. For `N` securities and `B` buckets, let `q, r = divmod(N, B)`; the
first `r` low-signal buckets contain `q + 1` rows, and the remaining buckets contain `q`.
Require every bucket to meet the declared minimum. Direction chooses the long and short
extremes after partitioning. There is no percentile interpolation or automatic bucket reduction.
Version-one documents are rejected; migration must supply the missing choices and create new
identities rather than reinterpreting a saved execution hash.

Conditional weights and cost estimates do not grant funding permission. For example, unit
long exposure consumes the pre-trade NAV, so positive fees can leave negative free cash when
short proceeds are segregated. Zero financing cost does not authorize that debit. An executor
must reject insufficient funding until an explicit permitted financing or reserve-sizing
policy exists. Fractional execution and rounding policies also remain execution gates.

The [closed formula language](formula-language.md) supplies arithmetic. Contracts additionally
check input names, dimensions and history: annual differences require two annual observations,
and compounded returns require a sufficient monthly return window. USD, shares and USD per
share are distinct units. Publication time cannot alias measurement, identity or revision
fields. Unknown held-security terminal outcomes and missing returns must fail accounting.

Content hashes include labels and evidence. A separate execution hash omits candidate labels
and source references but retains research choices and exact numeric literal spelling.
Whitespace and input-list order do not create a new execution. This detects identical declared
execution contracts; it does not establish algebraic equivalence or scientific novelty.

## Planning queue

`rank_hypotheses` accepts at most 64 candidates and an aware assessment time. It verifies
canonical manifests, permitted local research use, declared coverage, security namespaces,
table identities, supported policies and referenced bytes. History coverage is a conservative
metadata check per dataset. Actual observations and calendar semantics need later row checks.
Each candidate has a 64 MiB unique-artifact admission limit, checked before reads. Verification
is per candidate; the queue can reread shared artifacts and is not a large-data execution path.

The fixed score is `0.4 * novelty + 0.3 * specificity + 0.3 * readiness`. Novelty and specificity
are bounded proposed scores, not measured quality. Readiness is computed from the contract
and artifact checks. Ties use the hypothesis ID. The highest-ranked ready copy of an execution
is retained; duplicates and blocked drafts remain visible with reasons and stable identities.
Saved queue records validate status, inventory and duplicate links when reloaded.

Readiness means the declared contract and its referenced bytes passed these checks. It does
not establish valid data rows, calendar completeness, investability, empirical performance,
sandbox permission or execution budget. An executor must recheck current rights and these
remaining gates; a saved queue is not a durable authorization grant.

Published-paper conventions outside this version remain unresolved. In particular, NYSE
breakpoints, fiscal-year-relative annual formation and source-specific eligibility rules are
not silently translated into the supported monthly/June, all-eligible contract.
