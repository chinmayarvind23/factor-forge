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

## Durable reservation boundary

`postgres_budgets.reserve_operation` requires an explicitly trusted `execute_research`
principal and locks the owner-scoped canonical run row before reading or changing the
ledger. Browser principals have no new capability. The worker supplies the operation and
aware clock; the original run determines request identity, start time, dollar ceiling,
wall allowance and experiment count. The operation ceiling is fixed at 128.

Migration `002_research_budgets.sql` stores one bounded canonical JSON ledger per run,
with a foreign key to its canonical owner-bearing record. Reload revalidates the ledger,
its exact canonical encoding, and every immutable limit against the original request.
The transaction commits before the function returns dispatch permission. Competing calls
for the same operation therefore produce only one true result across connections.

A crash before commit rolls back the reservation. A crash after commit leaves an unresolved
reservation, and a new worker receives false for that operation even after the deadline.
This prevents automatic duplicate dispatch but does not establish that an external provider
executed the first call. No endpoint invokes this boundary yet.

`settle_operation` uses the same transaction and owner checks to attach a retained result
and controller-supplied charge. It requires an existing reservation before artifact access,
limits the result reference to one MiB, and checks returned byte type, length and SHA-256
against a separate expected reference. The provider receives a detached copy of that reference.
The caller must retain provider billing evidence; a content hash alone does not prove a charge.

An exact settlement replay is idempotent. Conflicting observations are rejected, including
changing an earlier unknown charge to zero. Late observations remain recordable, and a
measured overrun stays visible in the ledger and prevents further dispatch. An invalid or
unavailable result leaves the reservation intact. Explicit reconciliation of unknown outcomes
and graph-node integration are the next layers.

## Monthly experiment worker

`monthly_worker.execute_monthly_operation` connects the trusted monthly executor to this
ledger. It derives an operation UUID from the canonical run UUID and exact `MonthlyRequest`
hash, reserves one experiment slot, executes the admitted strategy, verifies publication of
its result, and settles zero LLM cost. The graph must retain the original request, including
its evaluation clock, for retry identity to remain stable.

A settled replay reads and validates the existing result bytes and request binding instead
of executing again. This applies to both completed backtests and retained domain failures.
A reservation without a settlement returns `RESEARCH_OPERATION_UNRESOLVED`; it is never
automatically dispatched again. Failpoints cover the gaps after reservation and before
settlement. A timeout or crash may therefore require explicit reconciliation even when
the artifact store already contains output.

This worker invokes the trusted local monthly accounting implementation. It provides no
generated-code execution, process deadline enforcement, public endpoint, or autonomous
literature-to-strategy decision. Those remain separate graph and sandbox responsibilities.
