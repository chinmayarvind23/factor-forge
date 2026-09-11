# Source-grounded direction review

`retrieval/direction_review.py` makes a separate model call using only the selected
strategy and verified source pages. It does not receive the initial extraction's
direction. The prompt defines the two direction labels and requests an exact quote
and page number, or an explicit uncertainty explanation.

Page size/hash checks precede decoding and provider execution. Source whitespace
is collapsed for the prompt. A supported judgment requires its exact quote to occur
in that normalized page, with a valid physical page number. The parser rejects
duplicate JSON keys, contradictory uncertainty and oversized responses. The prompt,
source packet, provider record, typed outcome and judgment are retained as artifacts.

Quote membership establishes source provenance, not semantic entailment. A model
can still misread an authentic quote. `supported` means a well-formed, source-cited
review observation; it is not an extraction-accuracy grade. A later coordinator
must compare it with the extraction and retain disagreements without overwriting
either observation. The review currently covers direction only.

The existing extraction prompt, its recorded development baseline and the original
live response remain unchanged. `orchestration/direction_review_worker.py` now wraps
the review in the existing PostgreSQL operation ledger. Its immutable command binds
the source packet, prompt SHA, fixed provider profile and maximum cost. The worker
reserves before delivery and passes the original run deadline to the provider.
Unknown dollar cost retains the full reservation. Settled replay verifies the saved
bytes and exact command before returning the original observation.

An interruption after reservation or after delivery but before settlement leaves an
unresolved operation. Retrying requires reconciliation and cannot dispatch another
model call. Four actual PostgreSQL integration cases cover both interruption windows
and restart recovery for supported and unavailable-provider outcomes. These controlled
responses verify durability, not model accuracy.

The version-two `ReviewedExperimentPlan` wraps an existing execution plan and an
explicit per-review cost allowance. Before dispatching a compiled candidate, the
scheduler requests this review and compares its direction to the retained extraction.
Only a supported matching judgment proceeds. Disagreement, uncertainty, invalid
provenance or provider unavailability produce a retained skip reason and consume no
experiment slot. Budget rejection produces `budget_stopped`; unresolved operations
still propagate for reconciliation. Both observations remain available in the final
`research-experiments-v2` artifact. Agreement establishes consistency between these
two observations; it does not prove their shared interpretation is correct.

Version-one plans and results retain their original schemas and canonical bytes.
The operator accepts either plan version by its explicit schema discriminator. The
review policy is part of a new request identity, so enabling review creates an
intentional new operator run rather than altering an earlier run's evidence.
