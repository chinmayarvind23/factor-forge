# Original equity tick engine spike

This directory prepares one real LEAN `Engine.Run` trial. The fixed C# algorithm
uses the already compiled launcher from
`lean-8ee075a-factorforge-dependencies-v1`. It does not replace the engine with a
portfolio formula. The algorithm compiled against the verified assemblies with zero
compiler warnings or errors and was packaged into a local image. Both compile
attempts confirmed container cleanup. The first failed because the inherited
`QCAlgorithm.Symbol` method shadowed `Symbol.Empty`; qualifying the type fixed it.
The packaged launcher has not yet executed this algorithm.

The source is original engineering data: ten SEC-A shares, average price 100,
cash zero, and prices 100, 102 and 104 at 20:00 UTC on April 29, April 30 and
May 1, 2024. SEC-A maps to one LEAN Equity symbol, FFA. The fixture uses a
synthetic always-open UTC exchange calendar; it does not claim NYSE session or
historical market coverage. Initial holdings are supplied inventory, not fills.
There are no orders, corporate actions, fees, cash interest or short positions.

`prepare.build_files` accepts only those declared source values and clocks. It
returns a fixed file inventory for the trusted controller to stage. It retains
the original JSON, canonical source, original map/factor rows, empty database
shells, three deterministic trade-tick ZIPs and a local-only configuration. The
algorithm registers the original UTC market-hours and USD symbol-property entry
before `AddEquity`. No upstream market dataset or reference NAV is staged.

The pinned [tick reader](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Data/Market/Tick.cs)
uses milliseconds after the data-date midnight and scales equity prices by
10,000. Each authored row therefore starts `72000000,1000000,1` for price 100 at
20:00 UTC, with corresponding values for the later rows. Quantity one is an
explicit synthetic tick-size encoding and is unrelated to the ten-share holding.
`Tick.EndTime` equals its instant. UTC data, exchange and algorithm time zones
avoid a daily-bar end-time conversion. The tick parser accepts decimal scaled
numbers, but this first translator is intentionally limited to the three integer
prices; it makes no claim about the entire gRPC decimal/timestamp domain.

During `Initialize`, the algorithm sets the first supplied market price and then
calls the security holding's `SetHoldings(average, quantity)`. This is necessary
because the pinned [algorithm manager](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Engine/AlgorithmManager.cs)
checks total NAV before applying the first feed update. No NAV is reported for
the preceding midnight-to-first-tick interval. In `OnData`, the algorithm checks
the actual tick clock and price, then reads `Portfolio.TotalPortfolioValue`
after LEAN updates the security. It never assigns the answer. A constant benchmark
and zero risk-free model avoid extra reference subscriptions; neither is used as
validation data. Any order event, changed inventory or missing row fails.

## Build and run after review

First verify all 322 compiled runtime files against the retained patched build
inventory and the exact two-package patch. Compile this project in the pinned
Microsoft SDK image using `build.sh`, an empty package-source configuration,
network none, two CPUs, 3 GiB RAM with no additional swap, 256 PIDs and a five-minute
deadline. Mount only the task-owned source/output/recipe plus the verified runtime
directory readonly. This project references those compiled assemblies and asks
for no new package. Missing references or native dependencies are failures for
review, not permission to fetch a new runtime or change engine accounting.

The packaging-only Dockerfile expects three bounded context directories:
`runtime/` with the verified patched output, `algorithm/` with the newly compiled
DLL, and `notices/` with retained upstream/package notices. The build controller
must bind source, patch, algorithm, configuration and output hashes to the final
image digest. The first local packaging produced
`sha256:337b3e29f39b9fbf1dba781b43469282649407c777df2362a737deda2ae724fb`.
No registry publication is part of
this spike. Packaging labels alone do not establish that the supplied directories
match the reviewed bytes.

The proposed execution profile is separate from Python v2: two CPUs, 2 GiB RAM
and equal memory-swap, 128 PIDs, 120 seconds, user/group 1654, readonly root and
input, all capabilities dropped, no-new-privileges, private PID/IPC/cgroup
namespaces, network none and the existing socket-denying seccomp asset. Use a
256 MiB `nosuid,nodev,noexec` scratch tmpfs, a 64 MiB equivalent `/tmp`, no inherited
Docker configuration, and at most 1 MiB combined stdout/stderr. Fixed environment:
`DOTNET_EnableDiagnostics=0`, `DOTNET_CLI_TELEMETRY_OPTOUT=1`,
`DOTNET_PROCESSOR_COUNT=2`, `HOME=/scratch`, `TZ=UTC`,
`FACTORFORGE_LEAN_SPIKE=1`. No caller argv, host path or environment reaches the
container. These are proposed limits awaiting the parent's runtime review.

The exact process command is:

```text
dotnet /app/QuantConnect.Lean.Launcher.dll --config /input/config.json
```

A controller-owned random name/label and full-ID verification must precede start.
Archive the start, exact input/source/image identity, created policy, bounded raw
output, exit/OOM and final cleanup. Timeout/cancellation must remove only that
owned container and confirm absence with a healthy daemon reply. No unconfined or
network-enabled retry is allowed. The existing launcher invokes `Engine.Run`;
an empty Python venv does not activate CPython, but native startup compatibility
still needs an actual run. The standard API object constructs clients; network
and socket denial remain necessary even for this offline configuration.

Accept only a clean launcher exit, three `FACTORFORGE_NAV:` rows with the exact
original clocks, Equity type, price/quantity/cash fields, `FACTORFORGE_DONE:3`, no
orders/fees and confirmed cleanup. Compare NAV against the separate predeclared
hand reference outside the engine. Do not use LEAN's aggregate strategy statistics
to grade this conditional valuation fixture. A successful trial would not yet
enable full gRPC readiness or establish trade/action/accounting equivalence.

The earlier ZIP compatibility result remains 10/11: a twelve-byte truncation
returned a missing entry instead of the expected exception. This spike generates
valid small archives and rejects missing observations; it does not rewrite that
failed oracle or establish general archive safety.
