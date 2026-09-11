# Unpromoted Python image candidates

The selected recipe is an installer-free Python 3.12.14 runtime candidate. It updates only
the existing `libuuid` package to Alpine's signed `2.42.3-r1` APK, then removes the complete
installed pip package, its metadata and entrypoints, and the complete `ensurepip` module
including bundled wheels. It inventories every removed file and rejects redirected paths.
This is a component removal, not a scanner-metadata exclusion.

`venv` remains supported with `with_pip=False`. Pip, `ensurepip`, and automatic pip
bootstrapping are intentionally unsupported. This candidate does not claim the full standard
library feature set. Future audited research dependencies can be installed during an isolated
build without shipping an installer in the final runtime.

Stage `remove_installers.py` and the exact APK identified in `provenance.json` into a dedicated
build context before using the Dockerfile. The recipe needs no network; APK signature checking
uses the official keys already present in the pinned base. Do not use `--allow-untrusted`.

The local feasibility controller executes the same recipe in one owned container with two
CPUs, 1 GiB memory, 256 PIDs, no network and a finite deadline, then commits and exports it.
A local commit is evidence of that build, not a reproducible registry identity or admission
to the research runner. Promotion still requires an unfiltered image scan, exact deployable
image identity and the complete real-container policy tests.

The measured local v2 image has an unfiltered zero-result scan; see the
[candidate report](../../../reports/security/python-sandbox-candidate-v2.json).
Docker Desktop inserted host mount paths into build labels in that image's configuration.
Publication must remove those labels in a separately hashed configuration, preserve its
relationship to the reviewed build and rerun acceptance against the resulting exact image.
Do not distribute the original export or treat its scan as acceptance of another digest.

`remediate.py` records the earlier rejected installer-preserving recipe. That attempt updated
pip and its bundled bootstrap wheel, but an image scan found vulnerabilities in pip's vendored
components. Its results must not be relabeled as a clean image.
