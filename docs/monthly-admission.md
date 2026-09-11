# Monthly source admission

`backtests.admission.admit_monthly` revalidates the v3 declaration and returns a typed
snapshot of its verified sources. This local library boundary requires a trusted artifact
store and an explicit aware assessment clock. It grants no remote-user capability and does
not turn model-authored rights statements into trusted ingestion metadata.

The v3 contract caps the complete unique reference inventory at 64 MiB before any read.
Admission reads manifests first. Each must be canonical JSON with the exact dataset identity,
permit local research at the assessment time, describe original fixtures, and declare the
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
