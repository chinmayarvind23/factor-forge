# Results

The browser/API brief flow, PostgreSQL persistence, LangGraph recovery and data foundation are
implemented. The original fixture has a replayable bundle with verified inputs and code.
There are no completed research benchmarks yet.
The target architecture in the design documents must not be interpreted as measured behavior.

| Measure | Evidence status |
| --- | --- |
| Autonomous research completion | Unmeasured; 45-case suite not frozen |
| Published-factor reproduction | Unmeasured; paper/data/tolerance records not frozen |
| FactorSpec extraction accuracy | Unmeasured for the release suite; separate three-paper critical-field pilot below |
| Benchmark lineage completeness | Unmeasured; no benchmark runs |
| Agent/tool spans | Unmeasured; tracing not implemented |
| Paired research runtime | Unmeasured; workload not frozen |
| Average LLM cost per paper | Unmeasured; local protocol calls have no dollar-cost measurement |

Engineering smoke tests establish package/build correctness only. Synthetic fixtures will be
reported separately from published-factor replication. Missing measurements are not zero scores.

At commit `ec9503d`, a clean Windows checkout passed 281 Python tests with 96.36% statement/branch
coverage. Two explicit skips cover unavailable audited DVC restoration and a POSIX-only FIFO
test. Another 49 artifact tests passed on Linux, with two Windows-only skips. Combining those
actual platform runs gives 97.997% coverage, including 100% for the bundle, catalog and
point-in-time selector. The suite includes real PostgreSQL failure/restart, RSA verification,
cancellation, artifact corruption and fixture-permission checks.
Nine Bun tests cover browser response/retry handling. Desktop/mobile Playwright checks exercise
real API submission and interrupted-request recovery. Workflow artifacts preserve browser evidence.

The same checkout created and replayed its saved fixture bundle and published/read back that
manifest through PostgreSQL. It preserves the unknown exit outcome and excludes future filings
from formation-time selection. It does not calculate a backtest or establish full research lineage.

Hosted Linux Python and web jobs pass. The complete release gate is blocked by the separate
[DVC dependency audit](../tools/dvc/README.md): diskcache has an unresolved advisory, and the
gate prevents DVC execution. An earlier real empty-cache restore passed before that finding;
it is functional evidence only. Live Cognito, S3 and deployment remain unverified. These
engineering checks do not measure research quality.

At clean commit `0badba9`, the expanded Windows suite passed 743 tests with 98.19% combined
statement/branch coverage and the same two explicit platform/tooling skips. This includes
real PostgreSQL integration and the literature, extraction, formula and hypothesis contracts.
The factor-contract and hypothesis modules reached 100% coverage; another 93 focused checks
passed on Linux. These counts describe engineering verification, not completed research runs.

At clean commit `e0b7d28`, 881 Windows tests passed with 98.40% combined statement/branch
coverage and the same two skips. The suite adds session-calendar planning, signed-share
accounting and conditional Polars target construction. Its Python build, formatting, lint
and strict typing checks passed. Hosted Python and web jobs also passed; the separate DVC
audit and complete release gate still failed. These conditional components have hand-checked
fictional examples, but do not yet execute a complete admitted strategy.

At clean commit `29f0d7d`, the completed conditional core passed 1,048 Windows tests
with two skips and one Starlette warning in 104.49 seconds. Combined statement/branch
coverage was 98.50%; Ruff, strict typing, source distribution and wheel builds passed.
The additions include monthly source assembly, artifact-backed target planning and
performance metrics. Four original target cases matched their hand references, and one
strict missing-signal case retained the expected failure. Eight original metric cases
matched 176 numeric/count checks. Their separate working-checkout artifact replay verified
40 objects and reproduced all eight outputs from saved inputs; it is separate from the
clean full-suite run. Funding, order admission, annual source assembly and continuous
full-strategy execution remain incomplete.

The [hosted workflow for `29f0d7d`](https://github.com/chinmayarvind23/factor-forge/actions/runs/34583861341)
passed Python and web jobs. Its DVC audit failed before restoration ran, and the required
release gate failed. The application dependency audit passed within the Python job.

## Python sandbox execution

The official Python image
`python@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79`
was pulled for local sandbox development. A Docker inspection on 11 September 2026
confirmed `linux/amd64`, image creation time `2026-09-01T00:12:40.129211396Z` and
46,182,573 bytes. A subsequent Docker Scout 1.19.0 scan indexed 132 packages and reported
33 vulnerabilities across 13 packages: 25 low, seven medium and one high. The scan exited
two with no requested severity or suppression filters. The [saved finding inventory](../reports/security/python-sandbox-image-v1.json)
binds the image, timestamp and raw SARIF hash. Debian's [CVE-2026-85091 tracker](https://security-tracker.debian.org/tracker/CVE-2026-85091)
lists the installed zlib source version as vulnerable and unfixed. Six pip findings list
fixed versions. Image remediation remains open; runtime acceptance does not clear these findings.

The [local operator runner](sandbox.md) now verifies source bytes, stages private inputs,
checks the created container against the fixed policy and saves bounded output and cleanup
replies. Its [pinned Moby seccomp derivative](../infra/sandbox/README.md) removes socket/network
allowances while retaining default denial and the remaining upstream restrictions.

Eight original real-Docker acceptance cases passed locally in 56.39 seconds: arithmetic,
syscall/filesystem denial, PID exhaustion, memory exhaustion, output limit, deadline,
cancellation and a child process outliving its Python parent. The cases retain source and
control artifacts, paired host-canary references and container-removal observations. These
are bounded engineering probes; they do not establish protection against every escape path.
A separate installed Windows CLI invocation completed through a work path containing spaces
and Unicode characters and removed its staging directory.

At clean commit `e439adf`, 1,422 Windows tests passed with seven explicit tooling/platform
skips and one Starlette warning in 110.17 seconds. Combined statement/branch coverage was
97.99%; formatting, lint, strict typing and source/wheel builds passed. This predates the
operator CLI and required Docker acceptance job added in `161a865`.

Clean commit `161a865` then passed 1,464 Windows tests in 114.71 seconds, with 15 declared
skips: DVC restoration, eight separately enabled Docker cases and six POSIX-only probes.
Reported combined coverage was 97.99%. One unreadable child coverage file was preserved and
excluded from that aggregate; its cause is unresolved. Ruff, strict typing and both package
builds passed. A separate real-Docker invocation passed all eight cases in 57.88 seconds.
Independent checks verified all saved reference bytes and 14 controller source modules per
run, the paired host canaries and owned-container removal. A separate environment installed
the fresh wheel and passed the operator CLI calculation and its 28-object evidence closure.

The [hosted workflow for `161a865`](https://github.com/chinmayarvind23/factor-forge/actions/runs/34587864317)
passed Python, web and the required real-Docker acceptance job. The Python job included its
application dependency audit; the web job included browser E2E checks. The separate DVC audit
failed before restoration, and the complete release gate failed. These are observed job/step
statuses; the hosted artifact closure has not yet been independently replayed.

At clean commit `a949e71`, the budget ledger and bounded LEAN gRPC contract brought the
Windows suite to 1,610 passing tests in 130.20 seconds, with the same 15 declared skips and
one Starlette warning. Combined statement/branch coverage was 98.14%; Ruff checked 187
formatted files, strict typing checked 131 source files, and source/wheel builds passed.
The checkout remained clean, with no child-coverage warning in this capture. The
[hosted workflow](https://github.com/chinmayarvind23/factor-forge/actions/runs/34590474141)
passed Python, web and real-Docker jobs; DVC still failed its audit before execution and
the release gate failed. These contract tests do not establish an execution-ready LEAN backend.

An unpromoted installer-free Python 3.12.14/Alpine 3.24 candidate updated the signed
`libuuid` package and removed the complete pip and ensurepip components. Scout 1.19.0
indexed 51 packages and reported zero findings in its September 11 snapshot. The
[candidate report](../reports/security/python-sandbox-candidate-v2.json) records the image
and raw scan hashes, supported smoke and remaining limitations. The original runner image
remains selected. Full runtime acceptance and a publication image without build-injected
host-path labels are pending; the scan alone does not justify promotion.

The sandbox uses a standard-library Python image and is separate from the research API.
Canonical run/FactorSpec admission, funding checks, full strategy execution, automatic crash
reconciliation and independent LEAN execution remain incomplete. A successful Python process
does not count as a completed research benchmark.

## Retrieval development pilot

At clean commit `42c66c2`, the frozen [three-paper pilot](../data/literature/three-paper-pilot-v1/README.md)
ran after 124 focused checks passed. BM25 ranked the relevant paper first for all six answerable
queries: Recall@3 and MRR@3 were both 1.0. It returned irrelevant results for all three no-relevant
queries, seven documents in total: false-positive query rate 1.0, abstention rate 0.0.
The [complete per-query report](../reports/retrieval/three-paper-bm25-v1.json) preserves both outcomes.
The corpus and judgments were committed before evaluation, and no threshold was tuned afterward.

These are three original summaries and manually targeted queries, not a representative retrieval
benchmark or a published-factor replication result. With three documents and `k=3`, Recall@3 alone
offers little discrimination. First-rank results and negative-query behavior are reported separately.
The saved local evaluation record is `60aa85c6e2df6b734053c98d085752380cef080df13ea52bed40edaf59310518`;
it preserves input bytes, configuration, code snapshots, environment and results.

## Source-extraction development pilot

At clean commit `3cc98ea`, one local `llama3.1:8b` attempt per paper matched **11 of 27
critical fields (40.74%)**, with **0 of 3 cases matching all nine fields**. Jegadeesh and Titman
matched 5/9; the Novy-Marx manuscript matched 6/9. Sloan's provider attempt failed and scored
0/9. The [per-field report](../reports/extraction/three-paper-local-v1.json) includes every case.
There were no retries, output repairs, or changes to the frozen gold after inference.

The selected strategy, source pages, exact request bytes, critical-field gold and numerical
vectors were frozen before the calls. This measures extraction given selected evidence, not
autonomous paper discovery or full FactorSpec construction. Formula grading requires the
closed arithmetic grammar, canonical input names and agreement on three numerical vectors.
The Novy-Marx formula used paper-style variable names, so it failed that declared executable
contract; this does not establish that its economic meaning was wrong. Formation-rule prose
and source entailment were not graded. The result is a development baseline, not the 15-paper
release extraction score or a factor-replication result.

The saved bundle is `970599cb0bab7efad0d91bed69c4719e11d83c76e63d214eed5f484a2c429ba3`.
It retains source hashes, requests, model identity, raw responses or failure captures, code,
environment, pre-call receipts and grades. Source PDFs and passages remain outside the public
repository because redistribution permission has not been established. Local dollar cost is
unmeasured. Before this run, 150 focused checks passed in the clean checkout; these are
engineering checks and do not increase the extraction score.

## Original direction development baseline

The ten original cases frozen in `33e4e86` completed with the existing source-only
reviewer and local `llama3.1:8b` profile. Seven observations met the direction criterion,
six met the cited-support criterion, and six met both. Direct high/low rules, signed
scores, strategy selection, the embedded instruction and negation met both criteria.
The quintile case met direction correctness; its quote omitted required supporting
context. Unspecified direction, a missing short leg and contradictory rules did not
meet the rubric's explicit uncertainty requirement.

Every saved grade was recomputed against the frozen cases, and all 64 artifacts
reachable from the evaluation verified by size and SHA-256. The evaluation reference
is `cd37472a47fd638f18616303b7d97305688dc6a7f39a8840ef2061e7b2ce362e`
(4,156 bytes). The suite reference is
`0f72560d1e57f27d1331a56a8ab16bfaa5f3b179ae9deddc0c4ee0a7b2b93375`.
The saved-result comparator accepted the baseline against itself without model calls.
These are original development cases; published-factor extraction, reproduction and
the 45-case autonomous benchmark retain their separate denominators. Local dollar
cost remains unmeasured. The [evaluation guide](../evals/README.md) defines the rubric
and layer status.

The fixed `complete-evidence-v1` candidate in `f483a71` completed the same ten cases
with five direction matches, three cited-support matches and three joint passes.
The comparator returned exit 1, retaining the six-pass baseline as the selected profile.
All 64 reachable candidate artifacts verified, along with each journal grade, recorded
observation, exact prompt and source-only model input. Its evaluation reference is
`974b6e034779164a70e3ff914c5eaac232a90fe59b1bf40e8de68b2292196847`
(3,769 bytes). There were no retries, response repairs or gold changes. The production
reviewer remains unchanged. This controlled comparison provides no basis for promoting
the candidate; further work should evaluate a distinct model capability hypothesis.

The `qwen3-baseline-v1` comparison frozen in `d41d222` used the original baseline
prompt with installed `qwen3:8b` and explicit non-thinking generation. It completed all
ten cases with **7/10 direction, citation and joint passes**, preserving all six baseline
joint passes and adding the quintile case. The three ambiguity cases remain development
work. The saved comparator returned exit 0. All 64 reachable artifacts verified, with
every actual model request checked for the frozen prompt, source input, model and limits.
Evaluation `84514fd743ffe7c056d5ba19af5f52b8267591240667b4a5cb524560c2fdea50`
contains 4,713 bytes. These exposed cases support further evaluation; production model
selection remains unchanged pending separate validation.

## Local model protocol evidence

A single 32,768-context protocol call timed out during model loading after 120.55 seconds.
A separately versioned 4,096-context, 128-output-token probe returned the requested JSON in
32.34 seconds, with 39 reported prompt tokens and 10 output tokens. Both attempts retain evidence.
The smaller probe establishes local delivery only. Neither is a paper extraction or a controlled
performance comparison, and neither measures dollar cost.
