"""Small command surface that grows only with implemented research operations."""

import argparse
import codecs
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from factorforge import __version__
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.fixture_bundle import (
    MAX_COMPONENT_BYTES,
    create_fixture_bundle,
    parse_saved,
    verify_fixture_bundle,
)
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError


def _pointer(path: Path) -> ArtifactRef:
    """Treat a saved pointer as bounded untrusted JSON without following its contents as paths."""
    try:
        with path.open("rb") as source:
            data = source.read(MAX_COMPONENT_BYTES + 1)
    except OSError:
        raise ResearchError(
            "BUNDLE_INVALID", "Bundle reference file is unavailable.", 422
        ) from None
    if len(data) > MAX_COMPONENT_BYTES:
        raise ResearchError("BUNDLE_INVALID", "Bundle reference exceeds the byte limit.", 422)
    try:
        if data.startswith(codecs.BOM_UTF8):
            data = data.decode("utf-8-sig").encode("utf-8")
        elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            data = data.decode("utf-16").encode("utf-8")
    except UnicodeError:
        raise ResearchError(
            "BUNDLE_INVALID", "Bundle reference encoding is invalid.", 422
        ) from None
    return parse_saved(data, ArtifactRef)


def main(argv: Sequence[str] | None = None) -> int:
    """Print JSON evidence or typed errors for fixture checks and install diagnostics."""
    parser = argparse.ArgumentParser(
        prog="factorforge", description="Quantitative research with reproducible evidence."
    )
    parser.add_argument("--version", action="version", version=f"FactorForge {__version__}")
    commands = parser.add_subparsers(dest="command")
    for name in ("fixture-bundle", "verify-bundle"):
        command = commands.add_parser(name)
        command.add_argument(
            "--output", type=Path, required=True, help="Owned local artifact directory"
        )
        command.add_argument("--repository", type=Path, default=Path.cwd(), help="Trusted checkout")
        if name == "verify-bundle":
            command.add_argument(
                "--ref", type=Path, required=True, help="Saved ArtifactRef JSON file"
            )
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        store = LocalArtifactStore(args.output)
        if args.command == "fixture-bundle":
            result = create_fixture_bundle(store, repository=args.repository).model_dump(
                mode="json"
            )
        else:
            result = verify_fixture_bundle(store, _pointer(args.ref), repository=args.repository)
        print(json.dumps(result, sort_keys=True))
    except ResearchError as error:
        print(
            json.dumps({"error": {"code": error.code, "message": error.message}}), file=sys.stderr
        )
        return 1
    return 0
