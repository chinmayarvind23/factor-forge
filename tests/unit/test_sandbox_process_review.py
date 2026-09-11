"""Independent controller probes cover process ownership, exact caps and literal transport."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from threading import Event, Timer
from typing import Any, cast

import pytest

from factorforge.domain.errors import ResearchError
from factorforge.sandbox.process import run_command


def capture_process(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[bytes]]:
    """Retain only the process launched by this test so cleanup can be checked directly."""
    launched: list[subprocess.Popen[bytes]] = []
    original = subprocess.Popen

    def tracked(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        """Record the concrete child without changing its controller configuration."""
        process = original(*args, **kwargs)
        launched.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", tracked)
    return launched


def assert_reaped(process: subprocess.Popen[bytes]) -> None:
    """Termination and closed pipe ownership are separate observable cleanup requirements."""
    assert process.poll() is not None
    assert process.stdout is not None and process.stdout.closed
    assert process.stderr is not None and process.stderr.closed


def test_midflight_cancel_reaps_launched_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancellation after process creation kills and reaps the owned controller."""
    launched = capture_process(monkeypatch)
    original = subprocess.Popen
    cancel = Event()
    timers: list[Timer] = []

    def delayed_cancel(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        """Start cancellation only once the real process exists."""
        process = original(*args, **kwargs)
        timer = Timer(0.1, cancel.set)
        timers.append(timer)
        timer.start()
        return process

    monkeypatch.setattr(subprocess, "Popen", delayed_cancel)
    try:
        result = run_command(
            (sys.executable, "-c", "import time; time.sleep(10)"),
            timeout_seconds=5,
            output_limit=32,
            cancel=cancel,
        )
        assert result.reason == "cancelled" and result.returncode is not None
        assert len(launched) == 1
        assert_reaped(launched[0])
    finally:
        for timer in timers:
            timer.cancel()
            timer.join()


@pytest.mark.parametrize("extra", [0, 1])
def test_exact_combined_limit_is_not_a_false_failure(extra: int) -> None:
    """Exactly filling the budget can exit successfully; one extra byte is a resource failure."""
    result = run_command(
        (sys.executable, "-c", f"import os; os.write(1, b'x'*17); os.write(2, b'y'*{15 + extra})"),
        timeout_seconds=5,
        output_limit=32,
    )
    assert len(result.stdout) + len(result.stderr) == 32
    assert result.reason == ("exited" if extra == 0 else "output_limit")
    if extra == 0:
        assert result.stdout == b"x" * 17 and result.stderr == b"y" * 15
        assert result.returncode == 0


@pytest.mark.parametrize(
    "kind",
    [
        "args_list",
        "empty",
        "arg_type",
        "nul",
        "arg_length",
        "args_count",
        "zero_time",
        "negative_time",
        "infinite_time",
        "nan_time",
        "huge_time",
        "overflow_time",
        "bool_time",
        "zero_limit",
        "huge_limit",
        "bool_limit",
    ],
)
def test_invalid_bounds_never_launch_a_controller(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Controller admission must reject malformed or oversized requests before process creation."""
    args: object = (sys.executable,)
    timeout: object = 1
    limit: object = 32
    if kind == "args_list":
        args = [sys.executable]
    elif kind == "empty":
        args = ()
    elif kind == "arg_type":
        args = (sys.executable, 3)
    elif kind == "nul":
        args = (sys.executable, "x\x00y")
    elif kind == "arg_length":
        args = (sys.executable, "x" * 16385)
    elif kind == "args_count":
        args = (sys.executable,) * 257
    elif kind == "zero_time":
        timeout = 0
    elif kind == "negative_time":
        timeout = -1
    elif kind == "infinite_time":
        timeout = float("inf")
    elif kind == "nan_time":
        timeout = float("nan")
    elif kind == "huge_time":
        timeout = 61
    elif kind == "overflow_time":
        timeout = 10**1000
    elif kind == "bool_time":
        timeout = True
    elif kind == "zero_limit":
        limit = 0
    elif kind == "huge_limit":
        limit = 1024 * 1024 + 1
    else:
        limit = True

    def forbidden(*args: Any, **kwargs: Any) -> None:
        """Any launch would violate the preflight expectation."""
        raise AssertionError("Popen should not be reached")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with pytest.raises(ValueError):
        run_command(
            cast(tuple[str, ...], args),
            timeout_seconds=cast(float, timeout),
            output_limit=cast(int, limit),
        )


def test_missing_controller_has_typed_unavailability() -> None:
    """Absent executables do not leak host diagnostics through the public error."""
    with pytest.raises(ResearchError) as caught:
        run_command(
            ("factorforge-review-no-such-controller-483e2",), timeout_seconds=1, output_limit=32
        )
    assert caught.value.code == "SANDBOX_CONTROLLER_UNAVAILABLE"
    assert "483e2" not in caught.value.message


@pytest.mark.parametrize("fault", ["set_blocking", "read"])
def test_pipe_io_fault_kills_and_reaps_owned_child(
    fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both pipe setup and reading errors must leave no live owned controller or open pipe."""
    launched = capture_process(monkeypatch)
    original_read = os.read
    original_blocking = os.set_blocking

    def bad_read(fd: int, count: int) -> bytes:
        """Fail only an already-created child's output pipe, preserving Popen's own internals."""
        if launched and launched[0].stdout is not None and fd == launched[0].stdout.fileno():
            raise OSError("synthetic private read failure")
        return original_read(fd, count)

    def bad_blocking(fd: int, blocking: bool) -> None:
        """Fail only the test-owned pipe's nonblocking configuration."""
        if launched and launched[0].stdout is not None and fd == launched[0].stdout.fileno():
            raise OSError("synthetic private configuration failure")
        original_blocking(fd, blocking)

    monkeypatch.setattr(os, "read", bad_read if fault == "read" else original_read)
    monkeypatch.setattr(
        os, "set_blocking", bad_blocking if fault == "set_blocking" else original_blocking
    )
    with pytest.raises(ResearchError) as caught:
        run_command(
            (sys.executable, "-c", "import time; time.sleep(10)"),
            timeout_seconds=5,
            output_limit=32,
        )
    assert caught.value.code == "SANDBOX_CONTROLLER_IO"
    assert len(launched) == 1
    assert_reaped(launched[0])


def test_shell_metacharacters_and_environment_remain_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit argv and environment transport neither invokes a shell nor inherits fake secrets."""
    monkeypatch.setenv("FACTORFORGE_REVIEW_INHERITED", "must-not-pass")
    environment = {"FACTORFORGE_REVIEW_EXPLICIT": "only-this"}
    if "SYSTEMROOT" in os.environ:
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    payload = '$(echo unsafe); & | < > ^ %PATH% `echo no` "quotes"'
    result = run_command(
        (
            sys.executable,
            "-c",
            "import json,os,sys; print(json.dumps([sys.argv[1],"
            "os.getenv('FACTORFORGE_REVIEW_EXPLICIT'),"
            "os.getenv('FACTORFORGE_REVIEW_INHERITED')]))",
            payload,
        ),
        timeout_seconds=5,
        output_limit=1024,
        environment=environment,
    )
    assert result.reason == "exited" and result.returncode == 0
    assert json.loads(result.stdout) == [payload, "only-this", None]


def test_background_controller_declares_no_window_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An API-launched Windows console controller should explicitly suppress interactive windows."""
    original = subprocess.Popen
    flags: list[int] = []

    def inspect_flags(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        """Inspect only the launch flag while preserving a real ordinary controller process."""
        flags.append(kwargs.get("creationflags", 0))
        return original(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", inspect_flags)
    result = run_command((sys.executable, "-c", "pass"), timeout_seconds=5, output_limit=32)
    assert result.reason == "exited"
    expected = 0x08000000 if sys.platform == "win32" else 0
    assert flags == [expected]
