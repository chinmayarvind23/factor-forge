# Evidence-based research reports

`infra/research/report.py` exports a report from a retained scheduler result. Use the
result SHA and size printed by the research operator:

```powershell
uv run python infra/research/report.py --artifacts artifacts/research --result-sha256 YOUR_RESULT_SHA --result-size YOUR_RESULT_BYTES
```

The command publishes typed JSON and Markdown artifacts, then writes
`report-<report SHA>.md` at the artifact directory root. Its relative links point to
local content-addressed evidence. Keep the Markdown file with that directory, or
adjust links when publishing elsewhere. Repeating the command returns identical
artifacts; a differing file at the expected export path is rejected. No model calls,
experiments, database changes or new budget reservations are required.

The report supports scheduler result versions one through three. It distinguishes
completed execution, stopped execution, held candidates and exhausted budget. It
shows original extraction, review and revision directions with links to their
records, any amendment, monthly result and requested validation artifact. Terminal
NAV comes from the retained account path, not a freely supplied report statistic.
The current report scope is original-fixture execution evidence; factor promotion
and published-factor reproduction are explicitly not assessed.

Before reporting, `lineage/closure.py` follows every explicitly typed artifact
reference reachable from the scheduler result and verifies its size and SHA-256.
Bounds are 512 distinct objects, eight MiB per object, 64 MiB total and 100,000 JSON
values per object. Empty non-JSON files are supported. Duplicate JSON keys,
conflicting reference metadata, missing objects and substituted bytes are rejected.
This is reachable-byte integrity, not proof of authorship or completeness against an
external lineage specification. Counts start at the scheduler result, excluding an
operator request that is not referenced from that result.

The builder rechecks bytes on consumption, validates source/run/plan alignment and
candidate indices, binds monthly outcomes to their exact original or amended draft,
checks capital and clock, re-derives amendments and checks HAC result/plan references.
A trusted caller must supply its canonical scheduler result; offline reports do not
grant access to another owner's data or certify research quality.

Three retained live runs have been exported and replayed with identical receipts.
All eleven exported artifact links resolve locally. Completed original execution and
amended execution are also covered by PostgreSQL integration tests; their report NAV
is checked against the original accounting fixture.

The research operator also accepts `--report`. Both commands share `report_export.py`,
so they produce the same report and Markdown bytes. The operator additionally records
a completion artifact containing the original request, scheduler result, settled
budget-ledger snapshot and report references. This provides a single root for those
explicitly linked artifacts. It does not replace canonical PostgreSQL state or claim
that the entire project's lineage specification has been fulfilled.
