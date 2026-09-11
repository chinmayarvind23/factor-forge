# Conditional signed-share accounting

`ledger_at` replays declared fills and corporate actions from an initial cash account.
`account_at` adds valuation at an exact observation time. These functions account for authored
conditional fills; they do not demonstrate that a strategy could discover, fund or execute them.
The ledger uses aggregate cash. It does not grant permission to spend segregated short proceeds.

Signed shares, cash and signed cash claims remain separate. A split changes shares once.
A dividend fixes the entitlement immediately before its cutoff, then converts that claim into
cash at payment. A known cash acquisition removes shares at its effective time and creates a
signed settlement claim. An unknown terminal value blocks any nonzero held exposure. A proved
earlier disposal may continue, retaining its realized gain or loss.

Availability timestamps are retained as information. They do not trigger economic booking.
This is ex-post accounting over an explicit event schedule; decision-time source selection
must separately enforce what was known. Effects precede payments and fills at a shared instant,
so buying exactly at dividend entitlement does not earn that dividend. Competing effects on the
same security at the same instant fail instead of receiving an invented ordering.

Identical event and fill IDs collapse only when all content agrees. Conflicting identities fail.
Effect and payment have separate phase identities. Each snapshot replays from the same initial
account; no hidden mutable state or late insertion into a previously mutated ledger is used.
Exited identities cannot be traded or receive a new economic effect under this profile.

Fills require matching, available, exact-time unadjusted USD quotes. Valuation requires an
exact-time available raw mark for every nonzero position. No stale or future mark fills a gap.
Contradictory prices for the same security and observation time fail even across source IDs.
Adjusted-return inputs are rejected to prevent applying a split or dividend twice.

Commission and slippage charge absolute traded notional. The initial pre-trade cash remains
the performance denominator, including entry fees. Borrow, financing and interest must each
be explicitly zero in this first profile; nonzero carry is rejected. No reinvestment or external
cash flows are inferred. Arithmetic uses an explicit 50-digit half-even Decimal context,
independent of process defaults. Inputs and output magnitudes are bounded; this does not imply
infinite-precision execution or an exchange's fractional-share policy.

JSON amounts must be decimal strings, such as `"1.000000000000000001"`. Numeric tokens
are rejected before conversion because binary-float parsing can erase a small difference
before Decimal validation. Python callers supply `Decimal` objects. Saved records already
use decimal strings, so this guard preserves their representation. The implementation uses
Pydantic's [before validators](https://docs.pydantic.dev/latest/concepts/validators/) to enforce
the wire contract before the bounded amount checks.

The original hand fixture checks nine scenarios and 50 close snapshots. For example, the
long split/dividend account ends at 1,080 from 1,000, while the short ends at 920. The mixed
account ends at 940, or 939 when its declared entry fees total one. These are fictional
engineering references, not observed market returns or published-factor replication.

The initial implementation passes 73 focused tests on Windows and Linux, including intraday
entitlement/payment, conflicting quotes, unknown exits, replay, malformed inputs and restored
state checks. Saved output validation checks inventories and return arithmetic, but an unsigned
snapshot alone does not prove complete experiment lineage or source authenticity.
