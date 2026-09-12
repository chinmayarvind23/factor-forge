# Source-driven scalar execution

This separate profile extends the seeded-price spike to actual LEAN orders for the
original twelve-return fixture. The translator stages the source strategy, point-in-time
signal facts, raw equity ticks, explicit borrow permission and local configuration.
No Python fills, NAV values or performance report enter the engine input.
The original UTC calendar closes weekends and retains the supplied weekday tick clocks.

The C# algorithm selects high/low signals available at formation, computes exact integer
shares from the declared capital and notional cost rate, and submits market orders at
the authored entry and liquidation clocks. It reads LEAN's actual order events and
portfolio values. The fee adapter implements the Python profile's explicit commission
plus slippage charge; it does not shift fill prices. The account uses LEAN's two-times
security margin model, an original weekday UTC equity calendar and zero risk-free
rate. No holdings or NAV are seeded.

The predeclared comparison requires 13 closing observations, including the $1002 baseline,
four fills (A +10 at 100, B -10 at 100, A -10 at 111, B +10 at 100), fees 1/1/1.11/1,
and final NAV $1107.89. The reference comes from the already retained Python execution,
whose full closing path has an independent arithmetic test. Expected output stays outside
the container. Clean engine exit, complete logs, no OOM and confirmed owned-container
cleanup are required in addition to numeric agreement.

Build against the previously verified pinned runtime using this directory's project and
recipe. Packaging adds only the compiled algorithm and retained notices to that runtime.
Use the same bounded, network-denied execution policy as the seeded spike, replacing its
environment marker with `FACTORFORGE_LEAN_EXECUTION=1`. Do not enable the seeded gRPC
profile for this different execution contract.

The v2 translator accepts admitted original scalar strategies with the A/B security
namespace, one formation, two equal-weight buckets, zero formation lag, one scalar
input and zero annual financing/interest/borrow charges. LEAN requires distinct signals,
unambiguous known membership, valid short permission and exact integer shares.
It does not establish general FactorSpec translation, historical exchange coverage,
arbitrary borrow/margin policies, corporate actions, financing charges or published-factor
reproduction. A successful compilation is not engine-verification evidence; actual trial
results must be recorded separately.

The actual weekday-calendar trial completed with **13/13 closing NAV matches and 4/4
fill matches**, including quantities, raw prices and fees. It reported total fees $4.11,
final NAV $1107.89, exit zero, no OOM, no engine errors and confirmed container cleanup.
The [captured comparison](../../../data/verification/lean-execution-v1/comparison.json)
contains the observations and evidence hashes. Compiled image:
`sha256:19995f31393fc4203648cdc7d5ee7ee135452b7bff72c2324e8c94e79e24e60d`.
The original always-open-calendar attempts also matched numbers but recorded missing-date
errors; the accepted trial closes weekends without changing source prices, orders or the
predeclared reference. LEAN's aggregate annualized performance statistics are not used
as evidence from this short authored sample.

The fee and margin interfaces were checked against the pinned upstream
[FeeModel](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Orders/Fees/FeeModel.cs)
and [SecurityMarginModel](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Securities/SecurityMarginModel.cs).


## Source contract v2

`build_strategy_files(repository, artifacts, spec, initial_cash=..., evaluated_at=...)`
admits and snapshots actual source bytes before staging. The engine derives its
formation, entry and exit clocks from the source calendar and sample dates, selects
the declared scalar concept and direction, and uses declared capital and costs.
No Python allocation, fills or NAV enter the source contract. Unsupported arithmetic
and time-series formulas are rejected. Ambiguous signal revisions are rejected by
this profile rather than resolved implicitly.

One compiled v2 image verified both original samples: 13 closing valuations and four
fills for the twelve-return case, and four closing valuations and four fills for the
short monthly case. Every comparison includes fees. Both engine runs exited cleanly
and their containers were removed. See the [v2 comparison](../../../data/verification/lean-scalar-v2/comparison.json).
This verifies source-driven sample dates in one executable; it does not establish
historical factor replication or general exchange/calendar coverage.

The earlier v1 trial and image above remain historical evidence. The v2 compiled image
is `sha256:c5a622dfe8f8612dfc6b0ada3c5aa894dc5dcd2aed895b1ff9ae539b443e04db`.

## Arithmetic source contract v3

The v3 contract adds a closed arithmetic tree for scalar input names, exact decimal
constants, unary signs, addition, subtraction, multiplication and division. Python
serializes syntax only. LEAN selects point-in-time source facts and evaluates the tree
with its own bounded rational interpreter, then ranks and trades the resulting scores.
Time-series calls remain outside this profile. The existing A/B universe, single
formation and integer-share funding limits remain.

The independently evaluated original hybrid has A = 7/4 and B = 3/2 from the declared
75% score / 25% quality blend. Its four closing valuations and four fills, including
fees, match the existing short reference. See the
[hybrid comparison](../../../data/verification/lean-hybrid-v3/comparison.json).
Exact rational score arithmetic can expose differences from Python's finite-precision
decimal evaluator on other inputs; agreement must be measured per case.

The standalone arithmetic checks link the production `ExactRatio.cs` directly and
need only the installed .NET 9 SDK, without LEAN or NuGet test packages:

```powershell
dotnet run --project infra/lean/arithmetic-tests/ArithmeticTests.csproj
```

The LEAN algorithm itself continues to compile against the pinned .NET 10 runtime.
Include both `ExecutedEquityAlgorithm.cs` and `ExactRatio.cs` in the build context.
