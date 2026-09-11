# Pinned LEAN source-build spike

This directory describes a build based on the QuantConnect LEAN launcher at
[`8ee075a39918f2df6fe9e0a5944e366fb60d10dc`](https://github.com/QuantConnect/Lean/tree/8ee075a39918f2df6fe9e0a5944e366fb60d10dc).
It is preparation for an independent engine adapter. A successful compilation
alone does not verify a strategy, accounting equivalence or offline execution.

The candidate identity is `lean-8ee075a-factorforge-dependencies-v1`.
`upstream-dependencies-v1.patch` replaces DotNetZip 1.16.0 with ProDotNetZip
1.20.0 and upgrades NetMQ 4.0.1.6 to 4.0.4.3. `dependency-patch.json` binds the
exact patch and observed source-file hashes. Those file hashes describe the
Windows checkout bytes; the patch itself uses canonical LF text. No engine
accounting source is changed. This is a patched dependency graph, so it must not
be described as an unchanged upstream build.

`images.json` pins the official Microsoft .NET 10 SDK and runtime linux/amd64
manifests. Microsoft documents these repositories in its
[container image guide](https://learn.microsoft.com/en-us/dotnet/core/docker/container-images).
Use the digest, not the mutable tag used to discover it. The September 11, 2026
observation measured 350,887,004 compressed SDK layer bytes and 83,146,609 runtime
layer bytes, with shared base layers. These are registry transfer sizes, not
memory budgets or vulnerability results.

## Build boundary

Acquire a depth-one, blob-filtered, sparse checkout of the pinned commit. Exclude
`Data` and `Tests`; do not acquire market datasets just to compile a launcher.
Keep source, output, package cache, recipe and Docker configuration in a fresh
task directory. Do not mount the project repository, a developer home, credential
files or the Docker socket into the build container.

Run `build.sh restore` inside the pinned SDK image, with only `NuGet.Config`'s
official HTTPS source enabled. Retain generated `packages.lock.json`,
`project.assets.json`, package hash files and build logs. Restore gets a network
namespace because it must acquire packages; this is a trusted build operation,
not the execution policy for generated strategies. The container does not enforce
a domain-level egress allowlist. No other network workload is authorized.

Run `build.sh audit` with the official source after restore. It reports vulnerable
direct and transitive packages as version-one JSON; bind its result to the actual
restored target and dependency graph. A clean report can omit `frameworks`, so
absence of that field alone must not establish a successful audit. The controller
also requires exit zero, complete capture and the expected project/source/query.

Run `build.sh compile` in a separate SDK container with `--network none`, sharing
only those task-owned source/cache/output directories. All phases use two CPUs,
3 GiB memory and equal memory-swap limits, 256 PIDs, user/group 1654, a readonly
root, all capabilities dropped and no-new-privileges. A 256 MiB non-executable
tmpfs supplies `/tmp`. One controller deadline caps the three phases at fifteen
minutes; a shorter in-container `timeout --signal=KILL` reserves time for cleanup.
The build uses Docker's default seccomp policy; the stricter Python execution
profile is not silently weakened to accommodate restore.

Use a nonce name and ownership label, inspect the created limits before start,
and preserve exit/OOM, raw logs and exact-ID cleanup replies. A failed transport
call never proves that the container was removed. Leave unrelated containers,
images and volumes alone; do not prune the daemon.

`Dockerfile.runtime` only packages the owned `output/runtime` directory. Its
context must contain that output and this Dockerfile, with no source repository
or credentials. Compilation is separate because a default BuildKit invocation
does not establish the explicit CPU/memory limits above. Publishing a local
runtime image does not authorize starting the launcher with its sample config.
A later reviewed adapter must supply a local-only configuration and original
inputs, enforce a separate runtime policy, and measure actual LEAN output.

## Acquisition and attribution

The initial Docker registry pull failed with TLS connection resets. Exact official
manifests and blobs were subsequently acquired through certificate-verified IPv4
HTTPS, checked against each descriptor's SHA-256 and size, and imported as OCI
archives. Docker resolved the original manifest references after import; inspected
filesystem diff IDs matched the official image configuration. No image filesystem
was extracted onto the host and no image contents were modified to make import
succeed. See Docker's [image load documentation](https://docs.docker.com/reference/cli/docker/image/load/).

LEAN is distributed under Apache 2.0. `LICENSE.QuantConnect` is the unchanged
license from the pinned source (SHA-256
`522cf0a716ce03f67d46f8fceb5bf78c5b84400ec5cd8d14bf9f02cddc1cb6ba`).
The recipe is FactorForge-authored; it changes no upstream engine accounting.
NuGet packages and Microsoft base images retain their own licenses. Retaining a
source license does not establish redistribution permission for arbitrary data
or clear every dependency advisory. No public LEAN market data is bundled here.

`LICENSE.ProDotNetZip` retains the fork's complete notices (Ms-PL and its listed
component licenses). Its package identifies source commit
[`0c4ac53a75af4fd2409dc7060477c998aff3bef5`](https://github.com/mihula/ProDotNetZip/tree/0c4ac53a75af4fd2409dc7060477c998aff3bef5).
`LICENSE.NetMQ` retains LGPL v3 and the independent-module linking exception at
source commit [`ca87d32d5ca5d8a2675fb7a9925e4b3dc8c35010`](https://github.com/zeromq/netmq/tree/ca87d32d5ca5d8a2675fb7a9925e4b3dc8c35010).
These notices do not relicense the dependencies as Apache 2.0 or finish a review
of every transitive package. The fork retains the `Ionic.Zip` namespace but uses
the `ProDotNetZip` assembly name; all consumers are rebuilt together.

The first build attempt reached Docker create but could not start because the
local log driver rejected compression with one retained file. The controller
then confirmed exact owned-container removal. The next attempt explicitly
disables log compression while retaining the 16 MiB log limit. Build and runtime
outcomes must be reported from their saved receipts, not inferred from this recipe.

The unchanged-source compiler subsequently exited 0 without OOM, but its warning
output exceeded the controller's original 1 MiB capture. That trial is recorded
as failed capture, with limited evidence of compilation feasibility. It produced
311 output files totaling 91,507,922 bytes; no strategy was executed. NuGet
reported unresolved high and critical dependency advisories, so those outputs
are not admitted runtime artifacts.

The current shell recipe retains a merged build log capped at 16 MiB, plus the
child's exit status. Reaching the log cap fails capture. Success, nonzero-exit
and cap-hit fixtures have exercised that function; a complete accepted build
using the revised capture is recorded separately from those failed attempts.

`compatibility/` contains original small ZIP fixtures, with independent framework
readers/writers and LEAN's compression API. The diagnostic has a container guard,
uses a private scratch directory and never starts the engine. Malformed/truncated
input and three extraction-boundary examples are finite checks; they do not
establish general archive safety or protection against decompression bombs.
The harness expects the reviewed compiled files mounted at `/runtime` and a
network-denied SDK container with the same build limits and a five-minute cap.

The September 11 derivative trial completed restore, audit and compilation in
316.422 observed seconds with a warm package cache. The audit reported no
vulnerable direct or transitive NuGet packages; the full compiler log was retained.
The verified output contains 322 files totaling 92,827,039 bytes. This is build
evidence, not a runtime image scan or a reproducibility timing claim.

The original ZIP diagnostic passed 10 of 11 cases in both its initial run and an
instrumented repeat. For a truncated archive, LEAN returned a missing entry;
the test expected a ZIP exception and failed through its missing-entry guard.
No price payload was returned. That discrepancy remains recorded rather than
being renamed a passing test. Both diagnostic containers exited 1 without OOM
and their removal was confirmed. No strategy has been executed with this build.
