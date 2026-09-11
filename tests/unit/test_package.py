"""Catch packaging and CLI regressions before a research runtime is added."""

import json
import subprocess
import sys
from pathlib import Path
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


def test_cli_bundle_creation_replay_and_typed_missing_pointer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI stdout supplies a portable pointer and replay returns the original-fixture selection."""
    repository = Path(__file__).resolve().parents[2]
    with TemporaryDirectory(prefix="factorforge-cli-") as directory:
        root = Path(directory)
        options = ["--output", str(root / "objects"), "--repository", str(repository)]
        assert main(["fixture-bundle", *options]) == 0
        pointer = capsys.readouterr().out
        assert len(json.loads(pointer)["sha256"]) == 64
        path = root / "reference.json"
        path.write_text(pointer, encoding="utf-8")
        assert main(["verify-bundle", *options, "--ref", str(path)]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["tier"] == "original_fixture"
        assert result["universe"] == ["SEC-A", "SEC-B", "SEC-C"]
        path.unlink()
        assert main(["verify-bundle", *options, "--ref", str(path)]) == 1
        captured = capsys.readouterr()
        assert not captured.out
        assert json.loads(captured.err)["error"]["code"] == "BUNDLE_INVALID"
        assert str(root) not in captured.err


def test_cli_rejects_oversized_pointer(capsys: pytest.CaptureFixture[str]) -> None:
    """A user-supplied pointer file cannot allocate unbounded memory or become a locator."""
    from factorforge.data.fixture_bundle import MAX_COMPONENT_BYTES

    with TemporaryDirectory(prefix="factorforge-cli-") as directory:
        root = Path(directory)
        pointer = root / "reference.json"
        pointer.write_bytes(b" " * (MAX_COMPONENT_BYTES + 1))
        assert (
            main(["verify-bundle", "--output", str(root / "objects"), "--ref", str(pointer)]) == 1
        )
        captured = capsys.readouterr()
        assert not captured.out
        assert json.loads(captured.err)["error"]["code"] == "BUNDLE_INVALID"
