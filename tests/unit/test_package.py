"""Catch packaging and CLI regressions before a research runtime is added."""

import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest

from factorforge import __version__
from factorforge.cli import main


def test_installed_package_works_outside_checkout() -> None:
    """A clean cwd prevents accidental source-path imports from masking packaging failures."""
    with TemporaryDirectory(prefix="factorforge-install-") as directory:
        result = subprocess.run(
            [sys.executable, "-m", "factorforge", "--version"],
            cwd=directory,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    assert result.stdout.strip() == f"FactorForge {__version__}"


def test_default_help(capsys: pytest.CaptureFixture[str]) -> None:
    """An empty invocation should explain the actual supported command surface."""
    assert main([]) == 0
    assert "--version" in capsys.readouterr().out


def test_unknown_command_is_rejected() -> None:
    """Missing research functionality must never return a successful-looking result."""
    with pytest.raises(SystemExit) as error:
        main(["research"])
    assert error.value.code == 2
