# Original monthly raw-price fixture

The inputs and independent expected outputs were frozen in commit `f1b0426` before the
strategy executor was implemented. They contain synthetic data for accounting verification.
The weekday calendar is authored and does not claim to be a real exchange holiday calendar.

`strategy.json` is the complete v3 declaration subsequently bound to those source bytes.
Its SHA-256 is `b4ee9859dd7611f2b8242f6bce678fe88c0251ca445b585d121b62e3bf514129`.
The execution request must separately bind initial cash of USD1002 to compare with this
reference. Two equal-weight buckets, six basis points commission and four basis points
slippage match the already-frozen declaration. No expected output is a strategy input.

The independent expected files retain their original hashes and explicitly describe their
scope and arithmetic conventions. A valid strategy declaration or source-admission receipt
must be followed by execution and comparison against the independent reference.
