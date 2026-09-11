# Monthly point-in-time signals

`assemble_monthly_signals(source_ref, store, request)` verifies an input-only artifact of
fundamental facts and historical membership. It produces a `CrossSection` for the
[conditional target planner](conditional-targets.md), together with selected fact provenance
and an explicit inventory of missing observations.

Each binding names a concept, exact unit and consecutive monthly history count. The source
contains monthly instant facts; annual fiscal periods and duration inputs require a separate
adapter. Formula names must match the signal bindings. An optional USD capitalization binding
is separate so an equal-weight signal does not require a weighting input it never uses.

Membership must be known and effective at formation. Facts must be published by that same
formation time, even when a later publication arrives before the trade. Economic lag changes
the requested period without moving the publication clock. Civil-month subtraction preserves
the day and clamps only to a shorter month: April 30 minus one month gives March 30, while
May 31 minus one month gives April 30. A June 28 formation never admits June 30 facts.

The adapter checks relevant known history for conflicting versions before choosing revisions.
It then indexes selected rows by security, concept, unit and calendar month. A requested month
with multiple eligible instant period ends fails as ambiguous. Missing months remain missing;
neither an older month nor another revision can fill the gap. Complete monthly decimal-return
histories can use `compound_return`. Invalid arithmetic and nonpositive capitalization fail
instead of becoming missing-signal exclusions.

Source objects are limited to 8 MiB, 50,000 facts and 10,000 membership events. Requests have
at most 32 formula bindings plus an optional capitalization binding, 120 observations per
binding, and 100,000 requested security/binding/month cells. The cell budget is checked before
fact indexing. Source JSON rejects duplicate members, nonfinite values and excessive nesting.
Decimal fact values use strings to preserve their precision before model validation.

Receipts bind exact source bytes and a request hash. They retain every eligible identity and
every selected or missing requested cell. Reload validates those inventories, selected context,
cutoffs and the scalar calculation. Authenticating selection against raw membership and all
revisions requires replay from the referenced source; a self-consistent receipt alone is
insufficient. Availability timestamps and input completeness remain source assertions.

The caller supplies a `FormationPlan`; this adapter does not fetch or admit its calendar.
It also does not grant data rights, validate a full FactorSpec's dimensional algebra, fund a
portfolio or execute trades. The upstream factor/calendar gates and downstream accounting
steps remain necessary for an admitted backtest.

The frozen original example supplies 52 facts, eight securities and two formations. The
integrated comparison matched all 16 scalar slots, 47 selected source rows and all four
equal/value target plans, including the missing May observation and resulting exclusion.
Its 22 referenced artifacts were independently verified. The comparison uses authored
decision times and establishes this conditional calculation only. The initial adapter suite
passes 66 tests on Windows and Linux.
