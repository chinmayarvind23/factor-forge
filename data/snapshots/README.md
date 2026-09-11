# Original fixture snapshot

`tiny-market-v1.json.dvc` was produced by DVC 3.67.1 from the exact bytes of
`data/fixtures/tiny-market-v1.json`. The native DVC MD5 is
`efb091859b54b8ad4a96c201f36c099c`; application SHA-256 is
`f0f075c544a78fa99ce27dadf615b5fc4d6bd68f0ebe7268591cdcc75ac4e36b`.

The output is ignored by Git. The original fixture remains available in Git so a clean
checkout does not need a private cloud remote to inspect these fictional test values.
Copying it here reconstructs the local snapshot; it does not demonstrate a DVC remote restore.
A real producer/push/empty-consumer/pull test passed against a local remote before the
dependency audit found an unresolved diskcache advisory. That is functional evidence only.

DVC is excluded from the application environment while its isolated tooling security gate
is unresolved. Do not treat this pointer as evidence of secure tooling, live S3 access,
historical equity-data coverage, or published-factor replication. No remote credentials or
machine-specific remote configuration are committed.
