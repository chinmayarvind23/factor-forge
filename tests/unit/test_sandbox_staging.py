"""Actual temporary files exercise verified staging without launching a container."""

import ctypes
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from test_experiments import IMAGE, OWNER, MemoryArtifacts, spec

from factorforge.domain.errors import ResearchError
from factorforge.domain.experiments import ExperimentAdmission
from factorforge.sandbox import staging
from factorforge.sandbox.policy import admit_experiment
from factorforge.sandbox.staging import staged_inputs


def admission(store: MemoryArtifacts) -> ExperimentAdmission:
    """A valid preflight receipt supplies fixed roles, not filesystem names."""
    return admit_experiment(
        spec(),
        store,
        principal=OWNER,
        image_digest=IMAGE,
        allowed_image_digests=frozenset({IMAGE}),
    )


def test_stage_exact_layout_inventory_permissions_and_cleanup() -> None:
    """The exposed mount contains only verified bytes and an explicit deterministic inventory."""
    store = MemoryArtifacts()
    receipt = admission(store)
    store.reads.clear()
    with TemporaryDirectory() as temporary:
        parent = Path(temporary)
        with staged_inputs(receipt, store, parent=parent) as mount:
            assert mount.name == "mount" and mount.parent.parent == parent
            assert (mount / "code.py").read_bytes() == b"print(1)"
            assert (mount / "config.json").read_bytes() == b"{}"
            assert (mount / "inputs" / receipt.spec.input_refs[0].sha256).read_bytes() == b"[1]"
            inventory = json.loads((mount / "inventory.json").read_bytes())
            assert inventory["schema_version"] == "experiment-input-inventory-v1"
            assert inventory["admission_sha256"] == receipt.sha256
            assert inventory["code"] == {
                "path": "code.py",
                "artifact": receipt.spec.code.model_dump(mode="json"),
            }
            assert inventory["config"]["path"] == "config.json"
            assert inventory["inputs"][0]["path"] == "inputs/" + receipt.spec.input_refs[0].sha256
            assert len(store.reads) == len(set(store.reads)) == 3
            if sys.platform != "win32":
                assert stat.S_IMODE(mount.parent.stat().st_mode) == 0o700
                assert stat.S_IMODE(mount.stat().st_mode) == 0o755
                assert stat.S_IMODE((mount / "inputs").stat().st_mode) == 0o755
                assert stat.S_IMODE((mount / "code.py").stat().st_mode) == 0o444
        assert list(parent.iterdir()) == []


def test_changed_store_bytes_reject_before_exposing_or_creating_bundle() -> None:
    """Admission is not a permanent attestation of mutable storage contents."""
    store = MemoryArtifacts()
    receipt = admission(store)
    store.data[receipt.spec.config.sha256] = b"[]"
    with TemporaryDirectory() as temporary:
        parent = Path(temporary)
        with pytest.raises(ResearchError) as error, staged_inputs(receipt, store, parent=parent):
            pytest.fail("Corrupt inputs must never be exposed")
        assert error.value.code == "SANDBOX_ARTIFACT_INVALID"
        assert list(parent.iterdir()) == []


def test_forged_admission_fails_before_reads_or_filesystem_work() -> None:
    """Revalidation prevents copied records from altering the authorized input closure."""
    store = MemoryArtifacts()
    receipt = admission(store).model_copy(update={"verified_refs": ()})
    store.reads.clear()
    with TemporaryDirectory() as temporary:
        with (
            pytest.raises((ResearchError, ValidationError)),
            staged_inputs(receipt, store, parent=Path(temporary)),
        ):
            pytest.fail("A forged receipt must not yield")
        assert store.reads == [] and list(Path(temporary).iterdir()) == []


def test_caller_exception_cleans_owned_bundle_without_masking_error() -> None:
    """Cleanup occurs during failed execution and preserves unrelated siblings."""
    store = MemoryArtifacts()
    with TemporaryDirectory() as temporary:
        parent = Path(temporary)
        sentinel = parent / "keep.txt"
        sentinel.write_bytes(b"unrelated")
        with (
            pytest.raises(RuntimeError, match="caller failure"),
            staged_inputs(admission(store), store, parent=parent),
        ):
            raise RuntimeError("caller failure")
        assert list(parent.iterdir()) == [sentinel]
        assert sentinel.read_bytes() == b"unrelated"


def test_same_admission_has_disjoint_concurrent_staging_paths() -> None:
    """Nested executions do not reuse mutable paths even with identical input identities."""
    store = MemoryArtifacts()
    receipt = admission(store)
    with (
        TemporaryDirectory() as temporary,
        staged_inputs(receipt, store, parent=Path(temporary)) as first,
    ):
        with staged_inputs(receipt, store, parent=Path(temporary)) as second:
            assert first != second
            assert hashlib.sha256((first / "code.py").read_bytes()).hexdigest() == (
                receipt.spec.code.sha256
            )
        assert first.exists() and not second.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink creation needs no Windows grant")
def test_parent_symlink_is_rejected_without_touching_target() -> None:
    """A trusted path that is replaced with a link cannot redirect staging or cleanup."""
    store = MemoryArtifacts()
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        target = root / "target"
        target.mkdir()
        link = root / "link"
        link.symlink_to(target, target_is_directory=True)
        with pytest.raises(ResearchError), staged_inputs(admission(store), store, parent=link):
            pytest.fail("A linked parent must not yield")
        assert list(target.iterdir()) == [] and link.is_symlink()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX descriptor cleanup race probe")
def test_replaced_mount_name_cannot_redirect_cleanup_to_other_files() -> None:
    """Descriptor-relative cleanup never walks an attacker-supplied replacement symlink."""
    store = MemoryArtifacts()
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        outside = root / "outside"
        outside.mkdir()
        sentinel = outside / "code.py"
        sentinel.write_bytes(b"keep")
        with (
            pytest.raises(ResearchError),
            staged_inputs(admission(store), store, parent=root) as mount,
        ):
            moved = mount.with_name("moved")
            os.rename(mount, moved)
            mount.symlink_to(outside, target_is_directory=True)
        assert sentinel.read_bytes() == b"keep"


@pytest.mark.parametrize("bad_bytes", [b"", b"not original", bytearray(b"{}")])
def test_reread_length_and_type_fail_closed(bad_bytes: object) -> None:
    """Staging checks actual return type and length independently of the store protocol."""
    store = MemoryArtifacts()
    receipt = admission(store)
    store.data[receipt.spec.config.sha256] = bad_bytes  # type: ignore[assignment]
    with TemporaryDirectory() as temporary:
        with (
            pytest.raises(ResearchError) as error,
            staged_inputs(receipt, store, parent=Path(temporary)),
        ):
            pytest.fail("Invalid bytes cannot yield")
        assert error.value.code == "SANDBOX_ARTIFACT_INVALID"
        assert not list(Path(temporary).iterdir())


def test_flush_failure_removes_all_created_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """A partially written bundle never leaks into an executor or survives successful cleanup."""

    def fail_flush(descriptor: int) -> None:
        """Inject a writeback failure before any completed mount can be exposed."""
        raise OSError("private filesystem details")

    store = MemoryArtifacts()
    monkeypatch.setattr(os, "fsync", fail_flush)
    with TemporaryDirectory() as temporary:
        with (
            pytest.raises(ResearchError) as error,
            staged_inputs(admission(store), store, parent=Path(temporary)),
        ):
            pytest.fail("Failed writes cannot yield")
        assert error.value.code == "SANDBOX_STAGING_FAILED"
        assert "private filesystem" not in str(error.value)
        assert not list(Path(temporary).iterdir())


def test_missing_parent_is_not_created() -> None:
    """The server provisions the trusted parent; staging cannot create arbitrary ancestors."""
    store = MemoryArtifacts()
    with TemporaryDirectory() as temporary:
        parent = Path(temporary) / "missing"
        with pytest.raises(ResearchError), staged_inputs(admission(store), store, parent=parent):
            pytest.fail("An absent server parent must not yield")
        assert not parent.exists()


def test_duplicate_input_roles_have_one_file_and_all_inventory_entries() -> None:
    """Repeated references preserve roles without repeated storage reads or conflicting creates."""
    store = MemoryArtifacts()
    request = spec(input_refs=(spec().config, spec().config))
    receipt = admit_experiment(
        request,
        store,
        principal=OWNER,
        image_digest=IMAGE,
        allowed_image_digests=frozenset({IMAGE}),
    )
    store.reads.clear()
    with (
        TemporaryDirectory() as temporary,
        staged_inputs(receipt, store, parent=Path(temporary)) as mount,
    ):
        assert len(list((mount / "inputs").iterdir())) == 1
        assert len(json.loads((mount / "inventory.json").read_bytes())["inputs"]) == 2
        assert len(store.reads) == 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native junction and handle behavior")
def test_windows_junction_parent_is_rejected_and_target_is_untouched() -> None:
    """A reparse ancestor is denied even when Windows would follow its directory target."""
    store = MemoryArtifacts()
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        target = root / "target"
        target.mkdir()
        junction = root / "junction"
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert created.returncode == 0
        try:
            with (
                pytest.raises(ResearchError),
                staged_inputs(admission(store), store, parent=junction),
            ):
                pytest.fail("A junction ancestor cannot yield")
            assert not list(target.iterdir())
        finally:
            junction.rmdir()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows pinned handle denies replacement")
def test_windows_live_mount_and_leaf_cannot_be_renamed() -> None:
    """Native handles deny delete sharing for the active directory and every staged leaf."""
    store = MemoryArtifacts()
    with (
        TemporaryDirectory() as temporary,
        staged_inputs(admission(store), store, parent=Path(temporary)) as mount,
    ):
        with pytest.raises(OSError):
            mount.rename(mount.with_name("replacement"))
        with pytest.raises(OSError):
            (mount / "code.py").rename(mount / "replaced.py")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX leaf identity replacement probe")
def test_replaced_leaf_is_not_followed_or_deleted_as_owned() -> None:
    """Cleanup rejects a substituted link while retaining the unrelated target bytes."""
    store = MemoryArtifacts()
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        outside = root / "outside"
        outside.write_bytes(b"keep")
        with (
            pytest.raises(ResearchError) as error,
            staged_inputs(admission(store), store, parent=root) as mount,
        ):
            (mount / "code.py").unlink()
            (mount / "code.py").symlink_to(outside)
        assert error.value.code == "SANDBOX_STAGING_CLEANUP"
        assert outside.read_bytes() == b"keep"


@pytest.mark.parametrize("failure", ["descriptor", "create"])
def test_windows_private_creation_native_failures_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """Native ACL/creation failures stop before exposing an unprotected directory."""
    if sys.platform != "win32":
        pytest.skip("Native Windows failure injection")
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    if failure == "descriptor":
        monkeypatch.setattr(
            advapi, "ConvertStringSecurityDescriptorToSecurityDescriptorW", Mock(return_value=0)
        )
    else:
        monkeypatch.setattr(kernel, "CreateDirectoryW", Mock(return_value=0))

    def library(name: str, *, use_last_error: bool) -> object:
        """Keep actual descriptor allocation/free while replacing only the selected failing call."""
        return advapi if name == "advapi32" else kernel

    monkeypatch.setattr(ctypes, "WinDLL", library)
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "private"
        with pytest.raises(ResearchError):
            staging._private_windows_directory(path)
        assert not path.exists()


def test_private_windows_helper_refuses_other_platforms() -> None:
    """Unsupported direct use cannot silently replace native ACL creation with weak defaults."""
    if sys.platform == "win32":
        pytest.skip("POSIX platform guard")
    with pytest.raises(RuntimeError):
        staging._private_windows_directory(Path("unused"))


def test_existing_random_name_is_never_cleaned_as_owned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exclusive-create collision cannot authorize deleting a preexisting directory."""
    chosen = Mock(hex="f" * 32)
    monkeypatch.setattr(staging, "uuid4", Mock(return_value=chosen))
    store = MemoryArtifacts()
    with TemporaryDirectory() as temporary:
        parent = Path(temporary)
        existing = parent / ("experiment-" + "f" * 32)
        existing.mkdir()
        sentinel = existing / "keep"
        sentinel.write_bytes(b"keep")
        with pytest.raises(ResearchError), staged_inputs(admission(store), store, parent=parent):
            pytest.fail("Collisions cannot be exposed")
        assert sentinel.read_bytes() == b"keep"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native DACL inspection")
def test_windows_private_directory_has_protected_owner_system_acl() -> None:
    """Inspect actual DACL entries without emitting account SIDs or private host paths."""
    store = MemoryArtifacts()
    with (
        TemporaryDirectory() as temporary,
        staged_inputs(admission(store), store, parent=Path(temporary)) as mount,
    ):
        command = (
            "$a=Get-Acl -LiteralPath $env:FACTORFORGE_TEST_PATH; "
            "@{protected=$a.AreAccessRulesProtected; "
            "sids=@($a.Access | ForEach-Object { "
            "$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value "
            "})} | ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            env=os.environ | {"FACTORFORGE_TEST_PATH": str(mount.parent)},
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert completed.returncode == 0
        observed = json.loads(completed.stdout)
        assert observed["protected"] is True
        assert set(observed["sids"]) == {"S-1-3-4", "S-1-5-18"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX replacement of an open regular file")
def test_replacement_regular_file_does_not_become_cleanup_owned() -> None:
    """Matching file type/name cannot replace the inode identity recorded by the open descriptor."""
    store = MemoryArtifacts()
    with TemporaryDirectory() as temporary:
        with (
            pytest.raises(ResearchError),
            staged_inputs(admission(store), store, parent=Path(temporary)) as mount,
        ):
            code = mount / "code.py"
            code.unlink()
            code.write_bytes(b"replacement")
        assert code.read_bytes() == b"replacement"


def test_cleanup_unlink_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """An OS refusal to remove an owned file never turns into a successful cleanup claim."""
    from factorforge.data.artifacts import _Anchor

    def denied_remove(self: _Anchor, name: str) -> None:
        """Inject a cleanup failure after real handles have been closed safely."""
        raise PermissionError("private cleanup path")

    store = MemoryArtifacts()
    with TemporaryDirectory() as temporary:
        with (
            pytest.raises(ResearchError) as error,
            staged_inputs(admission(store), store, parent=Path(temporary)),
        ):
            monkeypatch.setattr(_Anchor, "remove_temporary", denied_remove)
        assert error.value.code == "SANDBOX_STAGING_CLEANUP"
        assert "private cleanup" not in str(error.value)


@pytest.mark.parametrize("allowed", [False, True])
def test_cleanup_gate_retains_complete_readonly_bundle_or_removes_it(allowed: bool) -> None:
    """One trusted decision preserves complete evidence when container removal is uncertain."""
    store = MemoryArtifacts()
    gate = Mock(return_value=allowed)
    with TemporaryDirectory() as temporary:
        with staged_inputs(
            admission(store), store, parent=Path(temporary), cleanup_allowed=gate
        ) as mount:
            originals = {
                path.relative_to(mount): path.read_bytes()
                for path in mount.rglob("*")
                if path.is_file()
            }
            directory_mode = mount.parent.stat().st_mode
            file_mode = (mount / "code.py").stat().st_mode
        gate.assert_called_once_with()
        if allowed:
            assert not mount.exists()
        else:
            assert mount.parent.stat().st_mode == directory_mode
            assert (mount / "code.py").stat().st_mode == file_mode
            assert {path: (mount / path).read_bytes() for path in originals} == originals
            # Renaming after exit proves retained Windows handles no longer deny deletion.
            moved = mount.with_name("retained")
            mount.rename(moved)
            moved.rename(mount)


@pytest.mark.parametrize("failure", [RuntimeError("private gate details"), 1])
def test_failed_cleanup_decision_retains_files_and_closes_handles(failure: object) -> None:
    """An exception or nonboolean decision cannot authorize destructive cleanup."""
    store = MemoryArtifacts()
    gate = (
        Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
    )
    with TemporaryDirectory() as temporary:
        with (
            pytest.raises(ResearchError) as error,
            staged_inputs(
                admission(store), store, parent=Path(temporary), cleanup_allowed=gate
            ) as mount,
        ):
            original = (mount / "code.py").read_bytes()
        assert error.value.code == "SANDBOX_STAGING_CLEANUP"
        assert "private gate" not in str(error.value)
        assert (mount / "code.py").read_bytes() == original
        moved = mount.with_name("retained")
        mount.rename(moved)
