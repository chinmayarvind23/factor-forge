"""Bounded trusted controller processes are separate from container lifecycle enforcement."""

import math
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Event
from typing import Literal

from factorforge.domain.errors import ResearchError


@dataclass(frozen=True)
class CommandResult:
    """Captured controller bytes and termination reason never assert container cleanup."""

    stdout: bytes
    stderr: bytes
    returncode: int | None
    reason: Literal["exited", "timed_out", "cancelled", "output_limit"]


def run_command(
    args: tuple[str, ...],
    *,
    timeout_seconds: float,
    output_limit: int,
    cancel: Event | None = None,
    environment: Mapping[str, str] | None = None,
) -> CommandResult:
    """Run server-built argv with bounded nonblocking pipes, never shell-generated commands.

    Python 3.12 supports nonblocking subprocess pipes on Windows and POSIX. Reading one
    bounded chunk per pipe avoids both unbounded communicate buffers and stalled reader
    threads. The container controller must separately kill and verify its owned container.
    """
    if (
        type(args) is not tuple
        or not 1 <= len(args) <= 256
        or any(type(arg) is not str or len(arg) > 16384 or "\x00" in arg for arg in args)
        or not args[0]
        or type(timeout_seconds) not in (int, float)
        or not 0 < timeout_seconds <= 60
        or not math.isfinite(timeout_seconds)
        or type(output_limit) is not int
        or not 0 < output_limit <= 1024 * 1024
    ):
        raise ValueError("Controller command exceeds its bounded contract")
    if cancel is not None and cancel.is_set():
        return CommandResult(b"", b"", None, "cancelled")
    started = time.monotonic()
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW
    else:
        creation_flags = 0
    try:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            bufsize=0,
            env=environment,
            creationflags=creation_flags,
        )
    except OSError:
        raise ResearchError(
            "SANDBOX_CONTROLLER_UNAVAILABLE", "Controller process is unavailable.", 503
        ) from None
    assert process.stdout is not None and process.stderr is not None
    streams = (process.stdout, process.stderr)
    buffers = (bytearray(), bytearray())
    active = {0, 1}
    reason: Literal["exited", "timed_out", "cancelled", "output_limit"] = "exited"
    try:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
        while active or process.poll() is None:
            if cancel is not None and cancel.is_set():
                reason = "cancelled"
                break
            if time.monotonic() - started >= timeout_seconds:
                reason = "timed_out"
                break
            received = False
            for index in tuple(active):
                try:
                    chunk = os.read(streams[index].fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    active.remove(index)
                    continue
                received = True
                remaining = output_limit - sum(len(buffer) for buffer in buffers)
                buffers[index].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    reason = "output_limit"
                    break
            if reason == "output_limit":
                break
            if not received:
                time.sleep(0.01)
    except OSError:
        raise ResearchError(
            "SANDBOX_CONTROLLER_IO", "Controller output could not be read safely.", 503
        ) from None
    finally:
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            raise ResearchError(
                "SANDBOX_CONTROLLER_UNCONFIRMED", "Controller termination is unconfirmed.", 503
            ) from None
        finally:
            for stream in streams:
                stream.close()
    return CommandResult(bytes(buffers[0]), bytes(buffers[1]), process.returncode, reason)
