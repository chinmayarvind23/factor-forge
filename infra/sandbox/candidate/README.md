# Python runtime image preparation

The selected recipe is an installer-free Python 3.12.14 runtime candidate. It updates only
the existing `libuuid` package to Alpine's signed `2.42.3-r1` APK, then removes the complete
installed pip package, its metadata and entrypoints, and the complete `ensurepip` module
including bundled wheels. It inventories every removed file and rejects redirected paths.
This is a component removal, not a scanner-metadata exclusion.

`venv` remains supported with `with_pip=False`. Pip, `ensurepip`, and automatic pip
bootstrapping are intentionally unsupported. This candidate does not claim the full standard
library feature set. Install reviewed research dependencies during an isolated
build without shipping an installer in the final runtime.

Stage `remove_installers.py` and the exact APK identified in `provenance.json` into a dedicated
build context before using the Dockerfile. The recipe needs no network; APK signature checking
uses the official keys already present in the pinned base. Do not use `--allow-untrusted`.

The local feasibility controller executes the same recipe in one owned container with two
CPUs, 1 GiB memory, 256 PIDs, no network and a finite deadline, then commits and exports it.
Before admission to the research runner, require an unfiltered image scan, an exact
deployable image identity and the complete real-container policy checks.

`publication_oci.py` packages only the exact reviewed original archive pinned in its source.
It verifies bounded tar members, JSON, descriptors, compressed layer hashes and decompressed
rootfs identities without extracting files. It removes the five enumerated private build
labels, preserves every other runtime field and all history, and writes a new config,
manifest and named OCI archive. Unexpected host paths in retained metadata cause rejection.
The source archive remains unchanged. Output files use exclusive creation.

```powershell
python infra/sandbox/candidate/publication_oci.py --source ORIGINAL.tar --output PUBLICATION.tar --report PUBLICATION.json
```
