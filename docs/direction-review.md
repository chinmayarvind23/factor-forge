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
live response remain unchanged. Durable review reservation/settlement and scheduling
integration are the next layer; this component alone is not yet an execution gate.
Its caller supplies the provider and is responsible for execution budgets/deadlines.
