"""Small command surface that grows only with implemented research operations."""

import argparse
from collections.abc import Sequence

from factorforge import __version__


def main(argv: Sequence[str] | None = None) -> int:
    """Expose install diagnostics without implying unimplemented research commands work."""
    parser = argparse.ArgumentParser(
        prog="factorforge", description="Quantitative research with reproducible evidence."
    )
    parser.add_argument("--version", action="version", version=f"FactorForge {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
