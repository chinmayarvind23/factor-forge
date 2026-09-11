"""Explicit local operator execution does not expand application or browser capabilities."""

import argparse
import json
import shutil
import sys
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Never
from uuid import uuid4

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import LocalArtifactStore, _directory
from factorforge.domain.errors import ResearchError
from factorforge.domain.experiments import ExperimentSpec
from factorforge.sandbox.docker import ENDPOINTS as ENDPOINTS
from factorforge.sandbox.docker import DockerRuntime
from factorforge.sandbox.runner import run_experiment
from factorforge.sandbox.staging import _Cleanup, _new_directory


class _Parser(argparse.ArgumentParser):
    """Argument errors disclose only a safe code, without echoing arbitrary supplied values."""

    def error(self, message: str) -> Never:
        """Preserve --help while routing invalid arguments through the JSON exit contract."""
        raise ResearchError("SANDBOX_CLI_ARGUMENTS", "Sandbox arguments are invalid.", 422)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """A duplicate member cannot select an alternative interpretation of the same request bytes."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def _constant(value: str) -> object:
    """Nonfinite JSON extensions are outside the experiment wire contract."""
    raise ValueError("Nonfinite JSON constant")


def _request(path: Path) -> ExperimentSpec:
    """Bound a regular nonlinked file before strict JSON parsing and always-on nested validation."""
    try:
        with (
            _directory(path.absolute().parent, create=False) as directory,
            open(directory.open_file(path.name), "rb", closefd=True) as source,
        ):
            raw = source.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError("Spec size limit")
        json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        return ExperimentSpec.model_validate_json(raw, strict=True)
    except (OSError, ValueError, RecursionError, ResearchError):
        raise ResearchError("SANDBOX_INPUT_INVALID", "Experiment input is invalid.", 422) from None


@contextmanager
def _configuration(parent: Path) -> Iterator[Path]:
    """Pin a fresh private empty Docker config and remove only its original empty directory."""
    with ExitStack() as stack:
        try:
            anchor = stack.enter_context(_directory(parent, create=False))
            config = _new_directory(
                stack, anchor, "docker-config-" + uuid4().hex, _Cleanup(), private=True
            )
        except OSError:
            raise ResearchError(
                "SANDBOX_CONTROLLER_UNAVAILABLE", "Controller configuration is unavailable.", 503
            ) from None
        yield config.path


def main(argv: Sequence[str] | None = None) -> int:
    """Run one explicitly authorized operator attempt and print only its bounded evidence pointer.

    --execute creates the fixed local operator principal for this invocation only. The spec
    must name that owner; canonical run/FactorSpec resolution remains outside this internal
    tooling boundary. The default seccomp asset is checkout-relative; installed use must
    supply the reviewed asset explicitly when it is not available in the working directory.
    """
    response: dict[str, Any] | None = None
    try:
        parser = _Parser(
            description="Run a bounded local Python experiment as a trusted operator.",
            allow_abbrev=False,
        )
        for name in ("spec", "artifact-dir", "work-dir"):
            parser.add_argument("--" + name, required=True, type=Path)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument(
            "--seccomp", type=Path, default=Path("infra/sandbox/python-no-network-v1.json")
        )
        parser.add_argument("--endpoint", choices=sorted(ENDPOINTS))
        args = parser.parse_args(argv)
        if not args.execute:
            raise ResearchError(
                "SANDBOX_EXECUTION_NOT_AUTHORIZED",
                "Explicit execution authorization is required.",
                403,
            )
        request = _request(args.spec)
        principal = Principal("factorforge-local", "sandbox-cli", frozenset({"execute_experiment"}))
        if (request.owner_issuer, request.owner_subject) != (principal.issuer, principal.subject):
            raise ResearchError("FORBIDDEN", "Experiment execution is not permitted.", 403)
        if sys.platform not in {"win32", "linux"}:
            raise ResearchError("SANDBOX_UNSUPPORTED", "Operator platform is unsupported.", 503)
        endpoint = args.endpoint or (
            "npipe:////./pipe/dockerDesktopLinuxEngine"
            if sys.platform == "win32"
            else "unix:///var/run/docker.sock"
        )
        executable = shutil.which("docker")
        if executable is None or not Path(executable).is_absolute():
            raise ResearchError(
                "SANDBOX_CONTROLLER_UNAVAILABLE", "Docker executable is unavailable.", 503
            )
        parent = args.work_dir.absolute()
        with _configuration(parent) as config:
            runtime = DockerRuntime(binary=Path(executable), endpoint=endpoint, config=config)
            response = run_experiment(
                request,
                LocalArtifactStore(args.artifact_dir),
                principal=principal,
                runtime=runtime,
                parent=parent,
                seccomp=args.seccomp.absolute(),
            )
        output = {name: response[name] for name in ("record", "status", "failure_code")}
        code = 0 if output["status"] == "completed" else 1
    except ResearchError as error:
        output = {
            "record": response.get("record") if response is not None else None,
            "status": "failed",
            "failure_code": error.code,
        }
        code = 1
    except Exception:
        output = {"record": None, "status": "failed", "failure_code": "SANDBOX_CLI_FAILED"}
        code = 1
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
