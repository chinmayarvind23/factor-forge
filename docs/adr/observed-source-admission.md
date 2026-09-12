# Observed source admission with retained transformation evidence

Status: implemented in local monthly execution and the PostgreSQL dataset catalog.

The executor previously admitted only authored fixtures. Changing that label alone would
leave normalized observations detached from provider responses and transformation choices.
ObservedDatasetManifest extends the dataset contract with one derivation per normalized
object: raw source references, normalizer code, parameters and timing evidence.

Admission preserves the existing typed economic sources. It checks all manifest rights
first, expands the provenance inventory, rejects conflicting hash metadata and preflights
the aggregate 64 MiB/128-object limit before source reads. Every admitted byte is pinned
for execution. Catalog publication and readback use the subtype-aware parser and verify
the full referenced inventory independently of the storage provider's success response.

The alternative was to archive only normalized tables. That makes execution replay
possible but leaves provider revisions and normalization changes harder to investigate.
Retaining both increases storage and transfer cost, which is bounded in this profile.
Identity transforms may share byte identity; artificially duplicating bytes adds no evidence.

Rights, provider timestamps and transformation correctness remain trusted ingestion
responsibilities. Archived code is not executed at admission, and a checksum does not
prove those semantic claims. Source-specific normalizers require their own validation.
Execution reports preserve observed versus fixture scope and retain the existing temporal,
borrow, corporate-action and funding gates. LEAN verification remains reference-only.
