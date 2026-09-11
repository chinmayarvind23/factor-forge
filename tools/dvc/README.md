# Isolated DVC tooling

DVC is required for dataset versioning but is installed separately from the application and its ordinary development tools. This project pins DVC 3.67.1 with S3 support and pip-audit 2.10.1; its own `uv.lock` records the dependency resolution.

**Security gate blocked:** diskcache 5.6.3, required by dvc-data, is affected by [PYSEC-2026-2447](https://osv.dev/vulnerability/PYSEC-2026-2447). On 11 September 2026 the advisory lists no fixed version and PyPI's latest release is 5.6.3. Isolation does not fix this vulnerability. The required DVC CI job audits before running DVC and fails on the finding. The complete release gate remains blocked even if application checks pass. No advisory suppression or failure-to-success conversion is permitted.

From the repository root, install and audit without invoking DVC:

```sh
uv sync --project tools/dvc --locked
uv run --project tools/dvc --locked pip-audit --format json
```

Stop when the audit fails, including network or audit-tool failures. After an upstream remediation is reviewed, update the pin and lock, obtain a clean audit, then run the restoration test using the isolated interpreter:

```sh
FACTORFORGE_DVC_PYTHON="$PWD/tools/dvc/.venv/bin/python" \
  uv run --locked pytest tests/integration/test_dvc_restore.py \
  -q -k test_real_dvc_restores_original_fixture_from_empty_cache
```

On Windows, set `FACTORFORGE_DVC_PYTHON` to the absolute `tools\dvc\.venv\Scripts\python.exe` path after a clean audit. The test audits that interpreter again before invoking DVC, so direct invocation also fails closed. With no interpreter configured, ordinary application tests report the restoration case as unavailable. An invalid supplied path, failed audit or failed DVC command fails the test. CI supplies the interpreter explicitly and cannot accept an unavailable-tool skip as restoration evidence.

The restoration test creates separate producer, consumer and local remote directories. It passes only selected OS startup variables and uses new private home, temporary, DVC site-cache and DVC configuration directories. It excludes inherited cloud/application credentials and Python/tool configuration. The test uses copied original fixture bytes and finite subprocess timeouts; it does not contact S3 or run pipeline commands. A virtual environment is package isolation, not an operating-system sandbox.

An earlier local restoration succeeded before the dependency finding was identified. That is engineering evidence of the byte-restoration flow, not a security acceptance result. New DVC execution is blocked until the audit passes. The application's ordinary audit covers its own environment; it does not certify this optional tool environment.
