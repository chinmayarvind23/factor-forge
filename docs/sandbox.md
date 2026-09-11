# Local Python experiment runner

Terminal diagnostics retain the attach client's exit code and reason, output references,
and the separate daemon inspection. Exit 137 alone never establishes OOM: the controller
requires the daemon's `OOMKilled` flag. A hosted acceptance run at `d41d222` recorded 137
with that flag false in both terminal and cleanup inspections. Its assertion stayed red.
Hosted acceptance now also saves bounded kernel/daemon journal tails, runtime versions
and a time-bounded container event query, including when tests fail. Docker retains only
the latest 256 events; these diagnostic files supplement the receipts and do not prove
complete event history. See [Docker event semantics](https://docs.docker.com/reference/cli/docker/system/events/).

Local sandbox admission requires cgroup v2 with the `cgroupfs` driver. The disposable
hosted runner explicitly selects that driver, matching local Docker Desktop. Kernel
evidence from a subsequent systemd-driver run confirmed the exact container's memory
cgroup kill while the daemon flag stayed false. Containerd documents a systemd scope
collection race that can remove OOM evidence before inspection in its
[v2.3.4 test script](https://github.com/containerd/containerd/blob/v2.3.4/script/critest.sh#L71).
The driver restriction preserves the existing OOM assertion and all resource limits.
It is a local worker prerequisite, not an EKS driver recommendation. The controller
never changes a user's daemon configuration; unsupported hosts fail preflight.

FactorForge has an internal synchronous runner for bounded Python experiments in a local
Docker Linux container. An original arithmetic smoke read its staged code as UID65532,
returned 5050 for `sum(range(101))`, exited zero with no OOM flag and recorded confirmed
container removal. This establishes that the selected image, staging permissions and
controller path work together. Eight original real-Docker acceptance cases also passed
locally: arithmetic, syscall/filesystem denial, PID limit, OOM, output cap, deadline,
cancellation and a child process outliving its Python parent. Their saved control replies
include removal and a healthy empty listing. These bounded probes do not establish protection
against every container escape. Hosted acceptance is a separate required workflow job.

The runner is separate from the browser research flow. Browser and existing Cognito
capabilities do not grant `execute_experiment`. It does not resolve a supplied run ID or
FactorSpec hash against canonical records, validate strategy funding, or interpret a
successful Python process as a completed research run. A trusted caller must supply those
admission checks before exposing execution through an application API.

## Request and authority

[`ExperimentSpec`](../src/factorforge/domain/experiments.py) is strict, frozen and revalidated
at boundaries. It contains experiment/run UUIDs, owner issuer and subject, a FactorSpec
SHA-256, code/config/input ArtifactRefs, an integer seed, engine `python` and profile
`python-bounded-v2`. Historical v1 declarations and records remain readable, but this worker
rejects v1 execution before artifact reads. Each code/config object is nonempty and at most 256 KiB; their media
types are `text/x-python` and `application/json`. At most 32 input references and 16 MiB
of unique source bytes are admitted.

[`admit_experiment`](../src/factorforge/sandbox/policy.py) reconstructs the principal,
requires execution capability and exact owner agreement before reading artifacts. The
server supplies the image allowlist independently of the request. Every unique object
is checked for byte type, size and SHA-256. No request field selects a host path, image,
command, mount, environment, daemon endpoint or resource override. An admission receipt
records validated inputs and declared policy; it is not runtime attestation.

## Fixed runtime profile

The image contains Python and its standard library, with pip and ensurepip removed. It does
not contain the FactorForge application, Polars or LEAN. The exact image reference is
`factorforge-python-runtime@sha256:d3f48bcda1df69a2e87baa63ab56d5883fa790e790c3c7b3c907dcc9097d57d4`.
The executor requires Linux/amd64, cgroup v2 and reported CPU, memory, swap and PID controls.
It requires a containerd image store with the exact repository digest and manifest image ID,
matching manifest descriptor, sanitized runtime Config and ordered filesystem diff IDs.
Classic configuration-only image identity is unsupported. The configuration object digest is
`sha256:f3418e6db48e622047d51483756f98a50346cb44f832e2b428a53f551192d3c3`.
The [OCI image specification](https://github.com/opencontainers/image-spec/blob/main/config.md#imageid)
distinguishes the configuration-based image ID from the manifest that references it.
The controller checks Docker's runtime Config subset; it does not claim to recompute the raw
configuration object digest from an inspection response.
Create uses `--pull never`; execution cannot download an image or install dependencies.
The [recorded image evidence](results.md#python-sandbox-execution) preserves the original
image's 33 findings and the sanitized image's zero-finding unfiltered scan. Eight local v2
acceptance cases passed, including absence of pip and ensurepip. Fresh hosted import and
acceptance remain required before claiming runtime promotion is complete.

CI retrieves `runtime.oci.tar` from the isolated artifact commit
`790c03618afc6defb12977d3844701a08b01565c`, requires exactly 21,227,520 bytes and
SHA-256 `9f7b76a6e035cb0a64066be9b7e7bf7db51f831011d43e3a62039324df411a99`,
then imports it into the disposable runner's containerd image store. The archive is
kept on a separate orphan Git branch after Release asset transfers failed. This adds
a 21 MB Git object but permits authenticated checkout with read-only CI permissions.
The source checkout contains no runtime binary. Enabling the image store changes only
the hosted sandbox job's daemon; local operators must prepare their own supported store.
The job pins Docker Engine and CLI 29.2.1, matching the locally exercised engine version,
and retains the imported image inspection even if preflight rejects it. The first hosted
trial imported successfully under the runner's Docker 28.0.4 but all eight cases stopped
at `SANDBOX_IMAGE_INVALID` before creating a container. Its log did not retain the image
inspection, so the particular rejected field is unproven. No compatibility fallback was added.

| Control | Fixed setting |
| --- | --- |
| CPU, memory, swap | One CPU; 512 MiB memory; memory-plus-swap equals memory |
| Process and descriptor limits | 64 PIDs; 256 open descriptors; zero core dump size |
| Attached execution | 30-second controller deadline; 1 MiB combined stdout/stderr |
| Filesystem | Readonly root and `/input`; nonrecursive bind; private mount propagation |
| Writable storage | `/tmp` tmpfs, 64 MiB, nosuid/nodev/noexec; `/dev/shm` 1 MiB |
| Identity | UID/GID65532; all capabilities dropped; no-new-privileges |
| Namespaces | Private PID, IPC and cgroup namespaces; no host namespace overrides |
| Networking | Docker `none` plus the pinned custom seccomp profile |
| Lifecycle | No restart, healthcheck, TTY, interactive stdin or Docker log driver |
| Command | Fixed Python executable/launcher; generated code is `/input/code.py` |

The [seccomp asset](../infra/sandbox/README.md) derives from a pinned Moby allowlist and
removes socket/network syscalls, including `socket`, `socketpair` and `socketcall`.
The executor verifies its exact bytes and rejects missing or changed policy. It does not
fall back to the daemon default or unconfined execution. Socket-dependent Python features
are outside this first profile. Runtime syscall-denial evidence is separate from the
static profile derivation and ordinary Python startup.

The Docker CLI receives an explicit local endpoint and a fresh empty controller-owned
configuration directory. The supported endpoint set contains Docker Desktop's Linux
named pipe and the local Unix socket; the current smoke used Docker Desktop on Windows.
There is no model-selected remote daemon or developer credential-helper configuration.
Only a bounded host environment is supplied to the CLI. The container inherits the pinned
image environment plus fixed HOME/Python/thread settings and the requested hash seed;
application secrets are not copied into it.

## Staging and execution

[`staged_inputs`](../src/factorforge/sandbox/staging.py) rereads and verifies the bounded
source closure before exposing a mount. An exclusive random private outer directory
contains `mount/code.py`, `mount/config.json`, `mount/inputs/<sha256>` and
`mount/inventory.json`. The inventory binds the admission hash, roles, references and
fixed relative paths. Repeated input roles share one physical input file. If code/config
also occur as input roles, their additional fixed-path copies add at most 512 KiB beyond
the unique-source limit, plus bounded inventory metadata.

On POSIX the outer directory is mode0700, mount/inputs mode0755 and files mode0444.
Windows uses a protected owner/SYSTEM DACL on the outer directory and readonly files.
Pinned ancestors reject links/reparse points; file handles remain open during execution.
Cleanup checks owned identities and removes known leaves followed by empty directories.
It never recursively deletes a path selected by a request.

[`run_experiment`](../src/factorforge/sandbox/runner.py) archives a start record before
container creation, then stages inputs and builds the fixed command. Before starting
code, the controller inspects ownership, image, mounts, namespaces, security settings,
resources, environment and exact launcher arguments against the required policy.
The launcher checks mounted code/config/input lengths and digests inside the container,
seeds the standard-library random generator and runs the code. Config bytes remain data
for that code to interpret; the staging layer does not validate their semantics.

The seed fixes Python's hash seed and standard-library PRNG initialization. It does not
make arbitrary programs deterministic: wall clocks, process ordering and other inputs
can still affect output. The 30-second bound applies to the attached execution command;
preflight, creation, inspection and cleanup have separate bounded controller calls.
Killing a timed-out Docker client alone cannot establish container termination.

## Results, evidence and cleanup

The start record retains input admission, controller source references, environment and
nonce. Control artifacts retain inspected runtime observations. The final record links
the start, result and controls; stdout and stderr remain bounded untrusted byte artifacts.
Saved source is evidence and is never imported as replay authority. Output is not a
validated financial result, and this runner does not execute deserialized output.

`ExperimentResult` distinguishes `completed`, `failed`, `timed_out`, `cancelled`,
`cleanup_unconfirmed` and prelaunch `unsupported`. Completed requires an identified
attempt, ordered UTC clocks, exit zero, explicitly false OOM and confirmed cleanup.
The current runner returns safe failure codes for unavailable or unsupported preflight
conditions. An ordinary failed create can record no ID and confirmed absence without
inventing exit, OOM or output observations. An indeterminate create remains uncertain
even if one later query finds no container, because the daemon may still finish creation.

The controller verifies the exact nonce label/name before removing a resource. A failed
daemon query never proves absence. If container cleanup remains uncertain, the staging
cleanup callback retains the entire private input bundle while closing host handles.
Callback failure also retains it and raises a typed error. Confirmed container cleanup
permits ordinary staged-file removal. Local staging deletion failures stay visible.

A controller crash can leave a container and private staging bundle. A process-local lock
admits only one in-flight runner invocation; it cannot coordinate separate worker processes.
Automatic crash reconciliation, a persistent queue, run-level budget admission and
full FactorSpec resolution are unfinished. Operators must preserve uncertain evidence;
there is no daemon-wide pruning or retry policy that can substitute for reconciliation.

Containers share a host kernel. Host administrators, a compromised daemon/kernel and
hostile same-account processes are outside this first boundary. Docker configuration
inspection, an arithmetic smoke and schema tests do not establish protection against all
escape paths. The [bounded LEAN gRPC contract](lean-verifier.md) is implemented with an
unavailable default backend; independent LEAN execution remains unfinished.

## Explicit operator CLI

`factorforge-sandbox` is a local operator entrypoint. It requires `--execute` and a spec
owned by issuer `factorforge-local`, subject `sandbox-cli`. The CLI creates that principal
for the invocation only. This explicit operator authorization does not expand browser/API
permissions or resolve a run/FactorSpec against canonical records.

Prepare the referenced objects in a local artifact store and an existing trusted work
directory. From a checkout with the reviewed seccomp asset and installed dependencies:

```text
uv run factorforge-sandbox --execute --spec experiment.json --artifact-dir artifacts/local/sandbox-objects --work-dir artifacts/local/sandbox-work --seccomp infra/sandbox/python-no-network-v1.json
```

The spec file is capped at 256 KiB; duplicate JSON fields, nonfinite constants, invalid
encoding and schema violations fail before Docker setup. Docker must already be installed
and the pinned image present. The CLI finds its absolute executable from the operator's
trusted PATH. It selects the local Docker Desktop Linux pipe on Windows or local Unix
socket on Linux; `--endpoint` accepts only those two values. There is no image override.

Each invocation creates a pinned, private empty Docker configuration directory and removes
only that original empty directory afterward. Unexpected files cause a typed cleanup
failure instead of recursive deletion. `--seccomp` defaults to the checkout-relative asset;
an installed wheel does not carry `infra/sandbox`, so supply the reviewed file explicitly
when running elsewhere. Its contents must match the fixed runtime digest.

The CLI prints compact JSON containing only `record`, `status` and `failure_code`, and exits
zero only for a completed runner result with successful CLI cleanup. A runner result that
exists before config-cleanup failure remains linked in the printed failure. Invalid
arguments, unavailable prerequisites and pre-run errors have no invented record. The
underlying runner preserves its normal start/control/result evidence and uncertain inputs.

## Focused checks

From the repository root, the contract and staging checks are:

```text
uv run pytest tests/unit/test_experiments.py tests/unit/test_experiments_review.py tests/unit/test_sandbox_staging.py tests/unit/test_seccomp_profile.py -q
```

These tests include native filesystem/ACL behavior and platform-specific cases. They do
not invoke the daemon. Required runtime acceptance must separately exercise the actual
pinned image and preserve network/resource denials, termination and cleanup observations.
