# Research operation budgets

[`orchestration/budgets.py`](../src/factorforge/orchestration/budgets.py) implements pure,
immutable reservation and observation transitions. The browser normalization flow does not
use it yet. The module neither executes work nor authenticates a caller or commits storage.
A worker must bind the ledger to the canonical owner, run and original request, serialize
mutations and persist each reservation before dispatch.

The ledger records run UUID, request hash, start clock, wall allowance, LLM cost ceiling,
experiment allowance and at most 128 operations. Currency uses integer millionths of one USD;
the maximum declared cost remains $100. Each operation has a UUID, request hash, kind and
worst-case LLM charge. Only the `llm` kind can reserve a nonzero LLM charge; an `experiment`
consumes one experiment slot, and every kind consumes an operation slot. Attempts remain
counted after completion, including failures or known zero-cost calls.

`reserve` returns the updated ledger and a Boolean indicating permission for a first dispatch.
An exact replay returns false, including after completion or expiry. A reused operation ID
with changed inputs fails. The Boolean is conditional on the caller committing the new state
and owning the canonical run; separate callers holding stale copies cannot safely dispatch
without transactional serialization.

Reservations and observations have contiguous event sequence numbers. Reload replays those
events, checking available capacity at each dispatch. A later refund cannot justify an earlier
reservation. Sequence numbers retain order when timestamps are equal, so a later overrun does
not erase work that was already validly admitted at that same instant.

Pending operations reserve their entire declared charge. `settle` attaches one immutable
controller observation with a result ArtifactRef and known charge or explicit unknown charge.
Known charges release unused dollars. Unknown charges retain the estimate; they are not
recorded as measured zero. A known charge above its estimate remains in the ledger and blocks
further dispatch, even when the overall ceiling still has room. Observations allow up to
$1,000,000 to preserve bounded overrun evidence rather than clamping it to the $100 allowance.

The worker must verify result bytes and billing provenance. This module cannot establish that
a provider's bill is correct, that a free local call has measured zero cost, or that an
experiment completed safely. Operation estimates must come from trusted pricing and bounded
requests. A model-supplied estimate cannot authorize spending.

The UTC deadline remains anchored to the original start across restart. Equality is expired.
A new reservation cannot precede the latest saved reservation or observation clock. Late
completion can still be recorded after the deadline. Active calls need separate monotonic
timeouts and cancellation; this pure module cannot terminate a process.

Observations are append-once and exact repeats are idempotent. Changing an unknown charge to a
known charge requires a future explicit reconciliation protocol; overwriting the earlier
observation is rejected. No automatic retry follows an unresolved dispatch. The bounded ledger
is a prerequisite for the research graph, not evidence of an autonomous research run or a
measured cost study.
