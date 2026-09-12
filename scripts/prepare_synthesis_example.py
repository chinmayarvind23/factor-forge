"""Prepare original multi-source research inputs before any local model call."""

import argparse
from pathlib import Path

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.synthesis_fixture import prepare_synthesis_fixture


def main() -> None:
    """Retain the complete source/data request exclusively; execution is a separate command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    request = prepare_synthesis_fixture(
        Path(__file__).resolve().parents[1], LocalArtifactStore(args.artifacts)
    )
    with args.request.open("xb") as output:
        output.write(request.canonical_bytes())
    print(request.sha256)


if __name__ == "__main__":
    main()
