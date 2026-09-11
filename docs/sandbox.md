# Local Python experiment runner

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
`python-bounded-v1`. Each code/config object is nonempty and at most 256 KiB; their media
types are `text/x-python` and `application/json`. At most 32 input references and 16 MiB
of unique source bytes are admitted.

[`admit_experiment`](../src/factorforge/sandbox/policy.py) reconstructs the principal,
requires execution capability and exact owner agreement before reading artifacts. The
server supplies the image allowlist independently of the request. Every unique object
is checked for byte type, size and SHA-256. No request field selects a host path, image,
command, mount, environment, daemon endpoint or resource override. An admission receipt
records validated inputs and declared policy; it is not runtime attestation.

## Fixed runtime profile

The initial image contains Python and its standard library. It does not contain the
FactorForge application, Polars or LEAN. The current allowlisted image identity is
`sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79`.
The executor requires Linux/amd64, cgroup v2 and reported CPU, memory, swap and PID controls.
It checks the repository manifest digest, actual image ID, OS, architecture and absence
of image-declared volumes. Docker image stores can identify the resolved image by its
manifest or configuration object; the controller pins both expected digests and verifies
the created container against the resolved ID. The pinned configuration digest is
`sha256:ec7d6c95cd3692a2e2d228a8b1ca74e4025b54121fcc4c5da6f09cfa473315ad`.
The [OCI image specification](https://github.com/opencontainers/image-spec/blob/main/config.md#imageid)
distinguishes the configuration-based image ID from the manifest that references it.
Create uses `--pull never`; execution cannot download an image or install dependencies.
Digest pinning establishes identity, not the absence of image vulnerabilities.

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
escape paths. Independent LEAN execution and a gRPC verifier remain planned.

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
