# Conditional LEAN verification contract

The [protobuf service](../src/factorforge/interop/lean/lean.proto) and its Python handler
implement FactorForge's `Health`, `Capabilities` and `VerifyStrategy` boundary. These are
FactorForge methods around the planned LEAN launcher integration. No listener or runtime
backend is installed by this module. The default handler is alive with engine readiness false.

The first declared profile is `lean-price-only-seeded-holdings-v1`: up to eight long holdings,
nonnegative initial cash and 128 explicit UTC raw-price snapshots. It has positive initial
NAV, USD prices and a complete stable security inventory at every instant. Orders, shorts,
fees, corporate actions, adjusted prices, cash interest and full FactorSpec admission are
unsupported. Seeding conditional holdings does not establish buying power or executed fills.

Source amounts travel as decimal strings with at most 18 significant digits and exponent
between -8 and 12. Scalars, initial quantity-times-average-cost, quantity-times-price products
and cumulative NAV must fit [.NET Decimal](https://learn.microsoft.com/en-us/dotnet/api/system.decimal?view=net-10.0)
exactly. The comparison uses exact decimal NAV at identical UTC instants. It does not introduce
a statistical tolerance or claim published-factor reproduction.

The request carries owner/run/verification identity, FactorSpec metadata hash and separate
source and reference ArtifactRefs. Each JSON object is bounded to 1 MiB and checked for actual
length, hash, duplicate fields, nonfinite values and schema consistency. The reference binds
the source identity and requested clocks. The trusted backend receives only the validated
source; expected NAV never enters its translation input. The caller's reference is not
automatically an independently frozen gold set.

An injected authenticated resolver constructs the principal. The handler requires
`execute_lean_verification` and exact issuer/subject agreement before artifact reads or backend
readiness checks. Existing browser capabilities do not include this permission. Canonical run
and FactorSpec lookup remain upstream admission responsibilities.

Generated messages use explicit scalar presence. Missing required fields, unknown fields and
unknown enum values fail before application admission. The 64 KiB method limit supplements the
`SERVER_OPTIONS` limits that a future host must apply before transport deserialization.
Generated bindings are reproduced byte-for-byte with the pinned compiler in the test suite.

The handler admits one in-flight operation. A finite client deadline is mandatory and capped
at 120 seconds; the backend receives an absolute monotonic deadline and cancellation event.
Cancellation is cooperative. The slot remains held until the backend returns. An exception,
malformed backend result or unconfirmed cleanup quarantines the adapter and makes subsequent
execution unavailable until external reconciliation permits a new instance.

Before calling the backend, a start artifact records the canonical request, verified source
and reference identities, admitted engine identity and prepared UTC clock. Preparation is
distinct from an attempted execution. Final records link the start and explicit attempt flag.
Failed start publication prevents execution. A late deadline can retain prepared intent without
claiming that the engine ran.

Outcomes include unsupported, unavailable, deadline, cancelled, busy, engine failure,
disagreement and verified comparison. Returned raw output is bounded and archived. Verification
requires complete observation clocks, unchanged backend identity and confirmed cleanup.
Runtime identity and raw-output interpretation remain the trusted backend's responsibility;
the schema cannot authenticate an engine merely because an object validates.

The future backend must preserve actual translator, configuration, controller, image and
control-evidence artifacts, including failed-process captures. The handler has no automatic
retry, durable status index or verification-ID idempotency. A crashed call cannot be retried
automatically as though no work occurred. Independent LEAN execution remains unverified, and
upstream engine dependency findings remain unresolved.

The 108 focused Windows and Linux tests cover the boundary and controlled backend fixtures.
They do not count as engine runs. Run them with:

```text
uv run pytest tests/unit/test_lean_contract.py tests/unit/test_lean_wire.py tests/unit/test_lean_service.py tests/unit/test_lean_generated.py
```
