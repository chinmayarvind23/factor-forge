# Exact allocation templates

`AllocationSpec` declares the bucket partition, direction, weighting and tie rules.
`build_allocation` uses the existing Polars join and partition calculation to produce an
`AllocationTemplate` with exact rational unit sleeves. Its `unit-sleeve-template` scope
does not specify pre-trade or post-fee NAV, collateral, borrowing, quotes or quantities.

The input hash binds the selected cross-section, source references, formation and missing
signal policy. A separate allocation hash binds the partition policy. The result retains
all eligible bucket members, including interior zero weights, and sorted exclusions.
Reloading it checks unique identities, bucket sizes, signs and exact sleeve sums. Those
checks establish record coherence; replay from source bytes is still needed to establish
that the source selection and resulting ranking are correct.

`PortfolioSpec` retains the complete v2 contract by adding its original pre-trade sizing,
unit gross exposures, segregated proceeds and zero cash return to these allocation fields.
`build_targets` calls the shared calculation and returns its original `TargetPlan` shape,
scope, input hash and complete portfolio identity. It retains the original public error
code. Four policy/result hash pairs captured before this refactor cover both directions
and both weighting rules; their canonical bytes remain unchanged.

This separation lets a new execution profile use the existing partition calculation while
declaring its own sizing and funding rules. An allocation template alone cannot authorize
an experiment or supply evidence that a strategy was executed.
