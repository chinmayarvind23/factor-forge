"""Bounded controller subprocesses must not accumulate unrestricted Docker output."""

import sys
from threading import Event

from factorforge.sandbox.process import run_command


def test_process_captures_separate_output_and_exit_status() -> None:
    """Fixed controller arguments pass directly to a process without shell interpretation."""
    result = run_command(
        (
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)",
        ),
        timeout_seconds=5,
        output_limit=1000,
    )
    assert result.returncode == 7 and result.reason == "exited"
    assert result.stdout.strip() == b"out" and result.stderr.strip() == b"err"


def test_combined_output_is_capped_and_process_is_stopped() -> None:
    """Output flooding yields only the allowed prefix and a distinct resource failure."""
    result = run_command(
        (
            sys.executable,
            "-c",
            "import os;\nwhile True: os.write(1, b'x'*4096); os.write(2, b'y'*4096)",
        ),
        timeout_seconds=5,
        output_limit=10000,
    )
    assert result.reason == "output_limit"
    assert len(result.stdout) + len(result.stderr) <= 10000
    assert result.returncode is not None


def test_wall_timeout_stops_the_controller_process() -> None:
    """Stopping a controller is measurable but does not itself claim its container was killed."""
    result = run_command(
        (sys.executable, "-c", "import time; time.sleep(5)"), timeout_seconds=0.1, output_limit=1000
    )
    assert result.reason == "timed_out" and result.returncode is not None


def test_cancelled_work_does_not_launch_a_process() -> None:
    """A cancellation already observed at admission prevents even a controller process launch."""
    cancel = Event()
    cancel.set()
    result = run_command(
        ("not-a-real-executable",), timeout_seconds=1, output_limit=1000, cancel=cancel
    )
    assert result.reason == "cancelled" and result.returncode is None
