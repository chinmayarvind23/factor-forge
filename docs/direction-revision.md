# Direction conflict revision

`retrieval/direction_revision.py` defines one additional source-reading attempt for
a concrete disagreement between an extracted direction and a supported review.
`DirectionRevisionRequest` freezes the source packet and both complete observations.
Agreeing, missing or unsupported judgments cannot enter this profile.

The fixed revision prompt presents both judgments as non-authoritative and asks for
a direction supported by an exact source quote, or explicit uncertainty. Prior record
size/hash checks precede the provider call. Source page verification, strict parsing
and exact quote membership use the same implementation as source-only review. The
original review prompt and record shape remain unchanged.

The new record uses `direction-revision-record-v1` and retains the source, prompt,
provider receipt, both prior judgments and new result. This is a model observation;
it neither edits a strategy nor grants execution permission. The trusted coordinator
must supply canonical prior worker results. Hash integrity alone does not establish
the authenticity of arbitrary caller-created observations.

Durable operation reservation, a bounded scheduler revision policy and amended-draft
publication are the next integration steps. The version-two scheduler continues to
hold disagreements. No live revision accuracy claim follows from controlled tests.
