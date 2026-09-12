# Original long/short execution trial

This separate profile extends the seeded-price spike to actual LEAN orders for the
original twelve-return fixture. The translator stages the source strategy, point-in-time
signal facts, raw equity ticks, explicit borrow permission and local configuration.
No Python fills, NAV values or performance report enter the engine input.

The C# algorithm selects high/low signals available at formation, computes exact integer
shares from the declared capital and notional cost rate, and submits market orders at
the authored entry and liquidation clocks. It reads LEAN's actual order events and
portfolio values. The fee adapter implements the Python profile's explicit commission
plus slippage charge; it does not shift fill prices. The account uses LEAN's two-times
security margin model, an original always-open UTC equity calendar and zero risk-free
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

The current implementation is deliberately restricted to this original source fixture.
It does not establish general FactorSpec translation, historical exchange coverage,
arbitrary borrow/margin policies, corporate actions, financing charges or published-factor
reproduction. A successful compilation is not engine-verification evidence; actual trial
results must be recorded separately.

The fee and margin interfaces were checked against the pinned upstream
[FeeModel](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Orders/Fees/FeeModel.cs)
and [SecurityMarginModel](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Securities/SecurityMarginModel.cs).
