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
value weighting. Long and short sleeves each have unit exposure, giving initial gross
exposure two. Short proceeds are segregated and cash earns zero. These are declared policies;
an engine must enforce funding and portfolio accounting before any execution can pass.
The [session calendar](session-calendar.md) binds canonical schedule bytes and rejects versions
that were unavailable at formation; calendar completeness remains an explicit source assertion.

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
