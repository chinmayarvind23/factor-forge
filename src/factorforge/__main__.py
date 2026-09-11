"""Keep module execution equivalent to the installed console entry point."""

from factorforge.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
