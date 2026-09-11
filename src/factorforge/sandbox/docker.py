"""Fixed local Docker transport keeps generated input away from daemon controls."""

import hashlib
import json
import os
import re
from pathlib import Path
from threading import Event
from typing import Any

from factorforge.domain.errors import ResearchError
from factorforge.sandbox.image_binding import PYTHON_IMAGE as PYTHON_IMAGE
from factorforge.sandbox.image_binding import PYTHON_REFERENCE, matches_publication
from factorforge.sandbox.process import CommandResult, run_command

SECCOMP_SHA256 = "9033f43b539af2002ca705475be2b8b6633a9fd1fae924c9f58adb8aebd8a334"
OWNERSHIP_LABEL = "org.factorforge.controller-nonce"
ENDPOINTS = frozenset({"unix:///var/run/docker.sock", "npipe:////./pipe/dockerDesktopLinuxEngine"})


def _failure(code: str = "SANDBOX_CONTROLLER_INVALID") -> ResearchError:
    """Daemon diagnostics stay private while callers receive bounded, stable failure codes."""
    return ResearchError(code, "Sandbox controller could not verify the requested operation.", 503)


def _identifier(value: str) -> str:
    """Full immutable container IDs cannot be flags, ambiguous prefixes or arbitrary names."""
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise _failure()
    return value


class DockerRuntime:
    """Trusted server configuration selects a local daemon; requests cannot override transport.

    The config directory must be a fresh, controller-owned empty directory, preventing Docker
    proxy environment injection and credential helpers inherited from a developer config.
    This class never treats a failed inspect as proof of removal.
    """

    def __init__(self, *, binary: Path, endpoint: str, config: Path) -> None:
        """Freeze explicit executable, local endpoint and minimal controller environment."""
        if endpoint not in ENDPOINTS or not binary.is_absolute() or not config.is_absolute():
            raise ValueError("Docker requires absolute server paths and a supported local endpoint")
        if not config.is_dir() or any(config.iterdir()):
            raise ValueError("Docker config must be an empty controller-owned directory")
        self.prefix = (str(binary), "--host", endpoint, "--config", str(config))
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TMP", "TEMP"}
        }
        self.environment.update({"DOCKER_CLI_HINTS": "false", "LANG": "C", "LC_ALL": "C"})
        self.cleanup_evidence: list[dict[str, Any]] = []
        self._record_cleanup = False

    def command(
        self,
        args: tuple[str, ...],
        *,
        timeout: float = 10,
        output_limit: int = 262144,
        cancel: Event | None = None,
    ) -> CommandResult:
        """Only internal methods supply argv; output and controller lifetimes are always bounded."""
        result = run_command(
            self.prefix + args,
            timeout_seconds=timeout,
            output_limit=output_limit,
            cancel=cancel,
            environment=self.environment,
        )
        if self._record_cleanup:
            self.cleanup_evidence.append(
                {
                    "argv": args,
                    "reason": result.reason,
                    "exit": result.returncode,
                    "stdout": result.stdout.decode("utf-8", "replace"),
                    "stderr": result.stderr.decode("utf-8", "replace"),
                }
            )
        return result

    def checked(self, args: tuple[str, ...]) -> bytes:
        """Successful exit and complete capture are prerequisites for control-plane evidence."""
        response = self.command(args)
        if response.reason != "exited" or response.returncode != 0:
            raise _failure()
        return response.stdout

    def object(self, args: tuple[str, ...], *, array: bool = False) -> dict[str, Any]:
        """Bounded trusted daemon JSON is shape checked before any security assertion."""
        try:
            value = json.loads(self.checked(args))
            if array:
                if not isinstance(value, list) or len(value) != 1:
                    raise ValueError
                value = value[0]
            if not isinstance(value, dict):
                raise ValueError
        except (ValueError, TypeError, RecursionError):
            raise _failure() from None
        return value

    @staticmethod
    def verify_seccomp(path: Path) -> None:
        """A changed or unavailable reviewed asset fails without any compatibility fallback."""
        try:
            with path.open("rb") as stream:
                raw = stream.read(15598)
            if len(raw) != 15597 or hashlib.sha256(raw).hexdigest() != SECCOMP_SHA256:
                raise ValueError
        except (OSError, ValueError):
            raise _failure("SANDBOX_POLICY_INVALID") from None

    def preflight(self, image: str) -> dict[str, Any]:
        """Accept one pinned image and Linux amd64 with active resource controls."""
        if image != PYTHON_IMAGE:
            raise _failure("SANDBOX_UNSUPPORTED")
        info = self.object(("info", "--format", "{{json .}}"))
        security = info.get("SecurityOptions")
        if (
            info.get("OSType") != "linux"
            or info.get("Architecture") != "x86_64"
            or info.get("CgroupVersion") != "2"
            # systemd scope collection can race containerd's terminal OOM read.
            or info.get("CgroupDriver") != "cgroupfs"
            or not all(
                info.get(key) is True
                for key in ("MemoryLimit", "SwapLimit", "PidsLimit", "CpuCfsPeriod", "CpuCfsQuota")
            )
            or not isinstance(security, list)
            or not all(isinstance(item, str) for item in security)
            or not any("name=seccomp" in item.split(",") for item in security)
        ):
            raise _failure("SANDBOX_UNSUPPORTED")
        actual = self.object(("image", "inspect", PYTHON_REFERENCE), array=True)
        if not matches_publication(actual):
            raise _failure("SANDBOX_IMAGE_INVALID")
        return {"daemon": info, "image": actual}

    def create_args(
        self,
        *,
        nonce: str,
        mount: Path,
        seccomp: Path,
        image: str,
        seed: int,
        launcher: str,
    ) -> tuple[str, ...]:
        """Resource controls and mounts are server built; generated code is only a mounted file."""
        if re.fullmatch(r"[a-f0-9]{32}", nonce) is None or image != PYTHON_IMAGE:
            raise _failure()
        if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
            raise _failure()
        if any(
            not path.is_absolute() or any(char in str(path) for char in ',\n\r"')
            for path in (mount, seccomp)
        ):
            raise _failure("SANDBOX_PATH_INVALID")
        self.verify_seccomp(seccomp)
        return (
            "create",
            "--name",
            "factorforge-" + nonce,
            "--label",
            OWNERSHIP_LABEL + "=" + nonce,
            "--pull",
            "never",
            "--platform",
            "linux/amd64",
            "--network",
            "none",
            "--read-only",
            "--user",
            "65532:65532",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--security-opt",
            "seccomp=" + str(seccomp),
            "--cpus",
            "1",
            "--memory",
            "536870912",
            "--memory-swap",
            "536870912",
            "--pids-limit",
            "64",
            "--runtime",
            "runc",
            "--ipc",
            "private",
            "--cgroupns",
            "private",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=67108864,mode=1777",
            "--shm-size",
            "1048576",
            "--log-driver",
            "none",
            "--restart",
            "no",
            "--no-healthcheck",
            "--ulimit",
            "nofile=256:256",
            "--ulimit",
            "core=0:0",
            "--mount",
            f"type=bind,src={mount},dst=/input,readonly,bind-recursive=disabled",
            "--workdir",
            "/tmp",
            "--hostname",
            "factorforge",
            "--env",
            f"PYTHONHASHSEED={seed}",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONPATH=",
            "--env",
            "PYTHONNOUSERSITE=1",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "OMP_NUM_THREADS=1",
            "--entrypoint",
            "/usr/local/bin/python",
            PYTHON_REFERENCE,
            "-B",
            "-s",
            "-P",
            "-c",
            launcher,
        )

    def inspect_owned(self, identity: str, nonce: str) -> dict[str, Any]:
        """Ownership must be observed before stopping or removing any concrete container."""
        value = self.object(("container", "inspect", _identifier(identity)), array=True)
        if (
            value.get("Id") != identity
            or value.get("Name") != "/factorforge-" + nonce
            or not isinstance(value.get("Config"), dict)
            or not isinstance(value["Config"].get("Labels"), dict)
            or value.get("Config", {}).get("Labels", {}).get(OWNERSHIP_LABEL) != nonce
        ):
            raise _failure("SANDBOX_OWNERSHIP_UNCONFIRMED")
        return value

    def verify_created(
        self,
        identity: str,
        *,
        nonce: str,
        mount: Path,
        seccomp: Path,
        image: dict[str, Any],
        seed: int,
        launcher: str,
    ) -> dict[str, Any]:
        """Check effective create-time policy before code starts; malformed replies fail closed."""
        value = self.inspect_owned(identity, nonce)
        try:
            host = value["HostConfig"]
            config = value["Config"]
            expected_host = {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "Privileged": False,
                "NanoCpus": 1000000000,
                "Memory": 536870912,
                "MemorySwap": 536870912,
                "PidsLimit": 64,
                "IpcMode": "private",
                "CgroupnsMode": "private",
                "PidMode": "",
                "UTSMode": "",
                "UsernsMode": "",
                "OomKillDisable": False,
                "ShmSize": 1048576,
                "Runtime": "runc",
                "AutoRemove": False,
                "PublishAllPorts": False,
            }
            if any(
                host.get(key) != expected or type(host.get(key)) is not type(expected)
                for key, expected in expected_host.items()
            ):
                raise ValueError
            if json.dumps(host.get("Ulimits"), sort_keys=True) != json.dumps(
                [
                    {"Name": "core", "Hard": 0, "Soft": 0},
                    {"Name": "nofile", "Hard": 256, "Soft": 256},
                ],
                sort_keys=True,
            ):
                raise ValueError
            for field, required in {
                "MaskedPaths": {
                    "/proc/acpi",
                    "/proc/asound",
                    "/proc/interrupts",
                    "/proc/kcore",
                    "/proc/keys",
                    "/proc/latency_stats",
                    "/proc/sched_debug",
                    "/proc/scsi",
                    "/proc/timer_list",
                    "/proc/timer_stats",
                    "/sys/devices/virtual/powercap",
                    "/sys/firmware",
                },
                "ReadonlyPaths": {
                    "/proc/bus",
                    "/proc/fs",
                    "/proc/irq",
                    "/proc/sys",
                    "/proc/sysrq-trigger",
                },
            }.items():
                entries = host.get(field)
                if not isinstance(entries, list) or not required <= set(entries):
                    raise ValueError
            if (
                host.get("CapDrop") != ["ALL"]
                or host.get("CapAdd")
                or host.get("Devices")
                or host.get("DeviceRequests")
                or host.get("DeviceCgroupRules")
                or host.get("Binds")
                or host.get("VolumesFrom")
                or host.get("PortBindings")
                or host.get("GroupAdd")
                or host.get("ExtraHosts")
                or host.get("LogConfig") != {"Type": "none", "Config": {}}
                or host.get("RestartPolicy", {}).get("Name") != "no"
                or host.get("Tmpfs") != {"/tmp": "rw,nosuid,nodev,noexec,size=67108864,mode=1777"}
            ):
                raise ValueError
            mounts = host["Mounts"]
            if (
                len(mounts) != 1
                or mounts[0].get("Type") != "bind"
                or mounts[0].get("Source") != str(mount)
                or mounts[0].get("Target") != "/input"
                or mounts[0].get("ReadOnly") is not True
                or set(mounts[0].get("BindOptions", {})) != {"NonRecursive"}
                or mounts[0]["BindOptions"]["NonRecursive"] is not True
            ):
                raise ValueError
            effective = value["Mounts"]
            if (
                len(effective) != 1
                or effective[0].get("Type") != "bind"
                or effective[0].get("Source") != str(mount)
                or effective[0].get("Destination") != "/input"
                or effective[0].get("RW") is not False
                or effective[0].get("Propagation") != "rprivate"
            ):
                raise ValueError
            network = value["NetworkSettings"]
            if (
                not isinstance(network["Networks"], dict)
                or set(network["Networks"]) != {"none"}
                or network.get("Ports")
            ):
                raise ValueError
            security = host["SecurityOpt"]
            if len(security) != 2 or "no-new-privileges=true" not in security:
                raise ValueError
            profiles = [
                entry.removeprefix("seccomp=") for entry in security if entry.startswith("seccomp=")
            ]
            self.verify_seccomp(seccomp)
            if len(profiles) != 1 or json.dumps(
                json.loads(profiles[0]), sort_keys=True
            ) != json.dumps(json.loads(seccomp.read_bytes()), sort_keys=True):
                raise ValueError
            expected_env = dict(item.split("=", 1) for item in image["Config"]["Env"])
            expected_env.update(
                {
                    "PYTHONHASHSEED": str(seed),
                    "HOME": "/tmp",
                    "PYTHONPATH": "",
                    "PYTHONNOUSERSITE": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "OMP_NUM_THREADS": "1",
                }
            )
            if (
                len(config["Env"]) != len(expected_env)
                or dict(item.split("=", 1) for item in config["Env"]) != expected_env
                or config.get("Entrypoint") != ["/usr/local/bin/python"]
                or config.get("Cmd") != ["-B", "-s", "-P", "-c", launcher]
                or config.get("User") != "65532:65532"
                or config.get("WorkingDir") != "/tmp"
                or config.get("Hostname") != "factorforge"
                or config.get("OpenStdin") is not False
                or config.get("Tty") is not False
                or config.get("AttachStdin") is not False
                or config.get("AttachStdout") is not True
                or config.get("AttachStderr") is not True
                or config.get("StdinOnce") is not False
                or config.get("Healthcheck", {}).get("Test") != ["NONE"]
                or config.get("Volumes")
                or config.get("Image") != PYTHON_REFERENCE
                or value.get("Image") != image["Id"]
                or value["State"].get("Status") != "created"
                or value["State"].get("Running") is not False
                or type(value["State"].get("Pid")) is not int
                or value["State"]["Pid"] != 0
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            raise _failure("SANDBOX_POLICY_MISMATCH") from None
        return value

    def find_owned(self, nonce: str) -> str | None:
        """A successful daemon listing proves owned-name absence; transport errors never do."""
        if re.fullmatch(r"[a-f0-9]{32}", nonce) is None:
            raise _failure()
        rows = self.checked(
            (
                "container",
                "ls",
                "--all",
                "--no-trunc",
                "--quiet",
                "--filter",
                "name=^/factorforge-" + nonce + "$",
            )
        )
        found = rows.decode("ascii").split()
        if len(found) > 1:
            raise _failure()
        if not found:
            return None
        identity = _identifier(found[0])
        self.inspect_owned(identity, nonce)
        return identity

    def remove_owned(self, nonce: str) -> bool:
        """Remove only an owned container; absence requires a healthy daemon reply."""
        self.cleanup_evidence = []
        self._record_cleanup = True
        try:
            identity = self.find_owned(nonce)
            if identity is not None:
                self.checked(("container", "rm", "--force", identity))
            return self.find_owned(nonce) is None
        except (ResearchError, ValueError, UnicodeError):
            return False
        finally:
            self._record_cleanup = False
