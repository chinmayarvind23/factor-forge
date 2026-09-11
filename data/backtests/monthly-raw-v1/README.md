# Original monthly raw-price fixture

The inputs and independent expected outputs were frozen in commit `f1b0426` before the
strategy executor was implemented. They contain fictional data for accounting verification.
The weekday calendar is authored and does not claim to be a real exchange holiday calendar.

`strategy.json` is the complete v3 declaration subsequently bound to those source bytes.
Its SHA-256 is `4a62885ef169662cced545b20b2f644cbade66091de476315b66f60e0bf0c9bb`.
The execution request must separately bind initial cash of USD1002 to compare with this
reference. Two equal-weight buckets, six basis points commission and four basis points
slippage match the already-frozen declaration. No expected output is a strategy input.

The independent expected files retain their original hashes and explicitly describe their
scope and arithmetic conventions. A valid strategy declaration or source-admission receipt
alone does not establish a successful execution, research result or published-factor replication.
