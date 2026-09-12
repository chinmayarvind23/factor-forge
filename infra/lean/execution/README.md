# Source-driven scalar execution

This separate profile extends the seeded-price spike to actual LEAN orders for the
original twelve-return fixture. The translator stages the source strategy, point-in-time
signal facts, raw equity ticks, explicit borrow permission and local configuration.
Python-generated fills, NAV values and output reports stay outside the engine input.
The original UTC calendar closes weekends and retains the supplied weekday tick clocks.

The C# algorithm selects high/low signals available at formation, computes exact integer
shares from the declared capital and notional cost rate, and submits market orders at
the authored entry and liquidation clocks. It reads LEAN's actual order events and
portfolio values. The fee adapter implements the Python profile's explicit commission
plus slippage charge; it does not shift fill prices. The account uses LEAN's two-times
security margin model, an original weekday UTC equity calendar and zero risk-free
rate. No holdings or NAV are seeded.

The comparison checks portfolio observations, fill quantities, raw prices and fees
against separately retained expected records. Expected output stays outside the
container. Complete logs, clean engine exit and owned-container cleanup are required
alongside accounting agreement.

Build against the previously verified pinned runtime using this directory's project and
recipe. Packaging adds only the compiled algorithm and retained notices to that runtime.
Use the same bounded, network-denied execution policy as the seeded spike, replacing its
environment marker with `FACTORFORGE_LEAN_EXECUTION=1`. Do not enable the seeded gRPC
profile for this different execution contract.

The v2 translator accepts admitted original scalar strategies with the A/B security
namespace, one formation, two equal-weight buckets, zero formation lag, one scalar
input and zero annual financing/interest/borrow charges. LEAN requires distinct signals,
unambiguous known membership, valid short permission and exact integer shares.
Admission rejects strategies outside this translation contract.

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

## Arithmetic source contract v3

The v3 contract adds a closed arithmetic tree for scalar input names, exact decimal
constants, unary signs, addition, subtraction, multiplication and division. Python
serializes syntax only. LEAN selects point-in-time source facts and evaluates the tree
with its own bounded rational interpreter, then ranks and trades the resulting scores.
Time-series calls remain outside this profile. The existing A/B universe, single
formation and integer-share funding limits remain.

The standalone arithmetic checks link the production `ExactRatio.cs` directly and
need only the installed .NET 9 SDK, without LEAN or NuGet test packages:

```powershell
dotnet run --project infra/lean/arithmetic-tests/ArithmeticTests.csproj
```

The LEAN algorithm itself continues to compile against the pinned .NET 10 runtime.
Include both `ExecutedEquityAlgorithm.cs` and `ExactRatio.cs` in the build context.

## Whole-share source contract v4

The current translator preserves the strategy's explicit quantity policy. `EntrySizing.cs`
independently derives the fresh two-sleeve ideal NAV from capital and total fee rate,
then divides by source prices using bounded rational arithmetic. The whole-share policy
truncates toward zero and checks actual costs and funded exposure before placing orders.
The exact policy continues to require integral quantities in this LEAN profile.

The LEAN profile admits one formation, two original securities and no corporate
actions. Include `ExecutedEquityAlgorithm.cs`, `ExactRatio.cs` and `EntrySizing.cs`
when compiling the algorithm.
