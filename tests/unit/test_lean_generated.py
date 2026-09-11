"""Pinned compiler output stays reproducible without hand-maintained generated bindings."""

import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory


def test_checked_in_bindings_match_pinned_proto_compiler() -> None:
    """Regenerate in an owned scratch directory and compare each normalized compiler byte."""
    assert version("grpcio-tools") == "1.83.1"
    root = Path(__file__).resolve().parents[2]
    relative = Path("factorforge/interop/lean")
    with TemporaryDirectory(prefix="factorforge-proto-") as temporary:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "grpc_tools.protoc",
                "-I",
                str(root / "src"),
                "--python_out=" + temporary,
                "--pyi_out=" + temporary,
                "--grpc_python_out=" + temporary,
                str(root / "src" / relative / "lean.proto"),
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, "Pinned protobuf compilation failed"
        for name in ("lean_pb2.py", "lean_pb2.pyi", "lean_pb2_grpc.py"):
            assert (Path(temporary) / relative / name).read_bytes().replace(b"\r\n", b"\n") == (
                root / "src" / relative / name
            ).read_bytes().replace(b"\r\n", b"\n")
