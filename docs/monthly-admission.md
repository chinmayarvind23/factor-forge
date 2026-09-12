# Monthly source admission

`backtests.admission.admit_monthly` revalidates the v3 declaration and returns a typed
snapshot of its verified sources. This local library boundary requires a trusted artifact
store and an explicit aware assessment clock. It grants no remote-user capability and does
not turn model-authored rights statements into trusted ingestion metadata.

The v3 contract caps the complete unique reference inventory at 64 MiB before any read.
Admission reads manifests first. Each must be canonical JSON with the exact dataset identity,
permit local research at the assessment time, match the declared dataset kind, and declare the
supported namespace, availability, membership, raw-price and exit policies. Coverage includes
the requested monthly warmup and sample end. A future retrieval timestamp is rejected.

Every manifest object must have a declared strategy role, and every role must match its
object's name, schema and complete artifact reference. All repeated roles are checked;
dictionary ordering cannot replace a conflicting table declaration. This first bounded
profile deliberately rejects manifests containing additional unused objects.

After all manifests pass, each remaining artifact is fetched once and independently checked
for byte type, length and SHA-256. Providers receive detached reference copies so they cannot
replace the expectation during a read. Unexpected provider exceptions become fixed typed
diagnostics while established artifact errors survive. Calendar bytes must also match their canonical form and
declared calendar ID. Existing strict source loaders parse the monthly facts, raw market
bundle and comparison intervals. Actual row counts must match manifest metadata.

The returned store view copies and pins the verified byte inventory. An execution reread
therefore cannot consume changed provider content or fetch an undeclared object. Output
publication forwards to the trusted provider and checks its returned identity; outputs are
not added to the admitted input inventory. Durable publication and output reread verification
remain the caller's responsibility.

The canonical receipt retains the full strategy hash, execution hash, assessment time,
sorted verified references, manifest identities and source-role references. It records source
admission only. Actual calendar formation, point-in-time selection, complete price and interval
coverage, action rejection, loan availability, exact funding and retained execution outcomes
remain executor gates.

## Observed sources

The local execution path also accepts `policies.dataset_kind = "observed"` with
`short_loan = "require_valid_finite_source_grant"`. Each dataset must use
`ObservedDatasetManifest`, declare `availability_policy = "explicit-source-availability"`,
and retain one derivation for every normalized object. Existing namespace, membership,
raw-price, coverage, exit and rights checks still apply.

Each derivation contains `object_name`, `raw_sources`, `normalizer`, `parameters` and
`timing_evidence`. The latter four fields reference archived bytes through `ArtifactRef`;
`raw_sources` is a nonempty tuple. Archive provider responses, the transformation code,
its configuration and the evidence supporting the availability timestamps. An identity
transformation may reference the same bytes as raw input and normalized output.

Admission verifies all hashes and pins the expanded inventory after checking every
manifest's rights. The combined strategy, source and provenance inventory is limited to
128 unique objects and 64 MiB. Conflicting metadata for one hash is rejected. Supplied
normalizer code is retained as evidence and is never executed by admission.

`PostgresDatasetCatalog.publish` and `get` preserve the observed subtype and verify raw
and transformation evidence as well as normalized tables. Owner isolation, publication
capabilities and retention checks apply to the complete declared dataset. Ingestion must
establish that the declared rights cover every referenced source.

These are trusted ingestion declarations: hashes prove retained identity, not that a
provider's timestamp is truthful or that a transformation is economically correct.
Provider-specific normalization and timing review precede publication. A model cannot
grant data rights or approve its own source interpretation. The
[SEC concept normalizer](sec-normalization.md) implements an offline fundamental-fact
adapter with accession-level timing evidence and complete-row accounting.

Controlled fixtures verify observed-declaration admission, offline execution replay,
complete provenance, aggregate limits and actual PostgreSQL readback. They are not
observed market measurements. Historical source acquisition, provider adapters, larger
universes and longer samples remain research work. The independent LEAN profile still
accepts only its original reference cases.
