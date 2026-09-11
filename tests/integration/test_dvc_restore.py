"""Optional DVC restoration requires an explicit interpreter and a passing security audit."""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


def dvc_python() -> Path:
    """Missing optional tooling skips; explicitly broken configuration fails the test."""
    configured = os.environ.get("FACTORFORGE_DVC_PYTHON")
    if configured is None:
        pytest.skip("DVC tooling unavailable: set FACTORFORGE_DVC_PYTHON after its audit passes")
    interpreter = Path(configured)
    if not interpreter.is_absolute() or not interpreter.is_file():
        raise AssertionError("Invalid external DVC interpreter")
    return interpreter


def isolated_environment(root: Path) -> dict[str, str]:
    """Keep OS startup essentials while excluding application and inherited tool settings."""
    permitted = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "LANG", "LC_ALL", "LC_CTYPE"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in permitted}
    directories = {name: root / name for name in ("home", "temp", "site", "global", "system")}
    for directory in directories.values():
        directory.mkdir(mode=0o700)
    environment.update(
        {
            "HOME": str(directories["home"]),
            "USERPROFILE": str(directories["home"]),
            "APPDATA": str(directories["home"]),
            "LOCALAPPDATA": str(directories["home"]),
            "XDG_CONFIG_HOME": str(directories["home"]),
            "XDG_CACHE_HOME": str(directories["home"]),
            "TMP": str(directories["temp"]),
            "TEMP": str(directories["temp"]),
            "TMPDIR": str(directories["temp"]),
            "DVC_SITE_CACHE_DIR": str(directories["site"]),
            "DVC_GLOBAL_CONFIG_DIR": str(directories["global"]),
            "DVC_SYSTEM_CONFIG_DIR": str(directories["system"]),
            "DVC_NO_ANALYTICS": "true",
            "PYTHONNOUSERSITE": "1",
            "PYTHONSAFEPATH": "1",
            "AWS_EC2_METADATA_DISABLED": "true",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(directories["home"] / "empty-gitconfig"),
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def audit_tooling(interpreter: Path, root: Path, environment: dict[str, str]) -> None:
    """Direct test invocation must pass the advisory gate before executing any DVC command."""
    try:
        completed = subprocess.run(
            [str(interpreter), "-m", "pip_audit", "--format", "json", "--progress-spinner", "off"],
            cwd=root,
            env=environment,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise AssertionError("DVC security audit unavailable; DVC execution is blocked") from None
    if completed.returncode != 0:
        raise AssertionError("DVC security audit failed; DVC execution is blocked")


def dvc(interpreter: Path, environment: dict[str, str], directory: Path, *arguments: str) -> None:
    """Use finite commands with private caches and safe failure messages."""
    try:
        completed = subprocess.run(
            [str(interpreter), "-m", "dvc", *arguments],
            cwd=directory,
            env=environment,
            capture_output=True,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise AssertionError("DVC command unavailable or timed out") from None
    if completed.returncode != 0:
        raise AssertionError(f"DVC {arguments[0]} failed in the isolated test workspace")


def test_real_dvc_restores_original_fixture_from_empty_cache() -> None:
    """A pointer alone must retrieve identical bytes after the tooling audit succeeds."""
    interpreter = dvc_python()
    fixture = Path(__file__).parents[2] / "data/fixtures/tiny-market-v1.json"
    expected = hashlib.sha256(fixture.read_bytes()).hexdigest()
    with TemporaryDirectory(prefix="factorforge-dvc-") as directory:
        root = Path(directory)
        environment = isolated_environment(root)
        audit_tooling(interpreter, root, environment)
        producer, consumer, remote = root / "producer", root / "consumer", root / "remote"
        for workspace in (producer, consumer):
            workspace.mkdir()
            dvc(interpreter, environment, workspace, "init", "--no-scm", "--quiet")
            dvc(interpreter, environment, workspace, "config", "cache.type", "copy")
            dvc(interpreter, environment, workspace, "remote", "add", "-d", "test", str(remote))
        shutil.copyfile(fixture, producer / "fixture.json")
        dvc(interpreter, environment, producer, "add", "fixture.json", "--quiet")
        dvc(interpreter, environment, producer, "push", "--quiet")
        shutil.copyfile(producer / "fixture.json.dvc", consumer / "fixture.json.dvc")
        assert not (consumer / "fixture.json").exists()
        assert not (consumer / ".dvc/cache").exists()
        dvc(interpreter, environment, consumer, "pull", "--quiet")
        assert hashlib.sha256((consumer / "fixture.json").read_bytes()).hexdigest() == expected


def test_dvc_environment_excludes_secrets_and_inherited_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Credentials, Python path and inherited DVC settings never enter restore subprocesses."""
    for key in ("AWS_SECRET_ACCESS_KEY", "RDS_DSN", "PYTHONPATH", "DVC_REMOTE", "PIP_INDEX_URL"):
        monkeypatch.setenv(key, "sensitive-fixture")
    with TemporaryDirectory(prefix="factorforge-dvc-env-") as directory:
        root = Path(directory)
        environment = isolated_environment(root)
        assert "sensitive-fixture" not in environment.values()
        for key in ("DVC_SITE_CACHE_DIR", "DVC_GLOBAL_CONFIG_DIR", "DVC_SYSTEM_CONFIG_DIR", "HOME"):
            assert Path(environment[key]).is_relative_to(root)
            assert Path(environment[key]).is_dir()


@pytest.mark.parametrize("configured", ["", "relative/python", "/absent-factorforge/python"])
def test_invalid_explicit_dvc_interpreter_fails(
    configured: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly requested restore fails rather than silently skipping broken tooling."""
    monkeypatch.setenv("FACTORFORGE_DVC_PYTHON", configured)
    with pytest.raises(AssertionError, match="Invalid external DVC interpreter"):
        dvc_python()


def test_failed_audit_prevents_every_dvc_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed security gate cannot accidentally fall through to restoration or a skipped test."""
    calls: list[list[str]] = []

    def rejected_audit(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        """Return an advisory failure while observing whether any DVC command follows it."""
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, b"sensitive-fixture", b"sensitive-fixture")

    monkeypatch.setenv("FACTORFORGE_DVC_PYTHON", sys.executable)
    monkeypatch.setattr(subprocess, "run", rejected_audit)
    with pytest.raises(AssertionError, match="DVC security audit failed") as failure:
        test_real_dvc_restores_original_fixture_from_empty_cache()
    assert "sensitive-fixture" not in str(failure.value)
    assert len(calls) == 1 and calls[0][1:3] == ["-m", "pip_audit"]


@pytest.mark.parametrize(
    "error", [OSError("sensitive-fixture"), subprocess.TimeoutExpired("sensitive-fixture", 120)]
)
def test_unavailable_or_timed_out_tooling_fails_safely(
    error: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Process startup/time limits fail closed without printing captured provider diagnostics."""

    def unavailable(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        """Inject a failure before any external executable can run."""
        raise error

    monkeypatch.setattr(subprocess, "run", unavailable)
    with pytest.raises(AssertionError, match="audit unavailable"):
        audit_tooling(Path(sys.executable), Path.cwd(), {})
    with pytest.raises(AssertionError, match="command unavailable"):
        dvc(Path(sys.executable), {}, Path.cwd(), "pull")
