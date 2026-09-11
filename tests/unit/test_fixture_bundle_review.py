"""Independent fixture-bundle probes distinguish replay integrity from invented permission."""

import json
import shutil
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from factorforge.cli import main
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.fixture_bundle import (
    CODE_PATHS,
    FIXTURE_PATH,
    MAX_COMPONENT_BYTES,
    FixtureBundle,
    create_fixture_bundle,
    parse_saved,
    verify_fixture_bundle,
)
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def workspace() -> Iterator[tuple[Path, LocalArtifactStore]]:
    """Keep altered input and Git metadata in one task-owned disposable checkout."""
    with TemporaryDirectory(prefix="factorforge-bundle-review-") as directory:
        root = Path(directory)
        checkout = root / "checkout"
        for relative in (*CODE_PATHS.values(), FIXTURE_PATH, "uv.lock", "data/fixtures/README.md"):
            target = checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        yield checkout, LocalArtifactStore(root / "objects")


def altered_component(
    store: LocalArtifactStore,
    pointer: ArtifactRef,
    key: str,
    content: bytes,
) -> ArtifactRef:
    """Rehash an altered graph component so semantic checks must do more than verify bytes."""
    graph = json.loads(store.get(pointer))
    graph[key] = store.put(content, media_type="application/json").model_dump(mode="json")
    return store.put(json.dumps(graph).encode(), media_type="application/json")


@pytest.mark.parametrize("change", ["permission", "terms", "missing_exit"])
def test_modified_fixture_cannot_inherit_original_public_rights(
    workspace: tuple[Path, LocalArtifactStore],
    change: str,
) -> None:
    """A fixed fixture command cannot promote modified data or terms into authorized content."""
    checkout, store = workspace
    source = checkout / FIXTURE_PATH
    data = json.loads(source.read_bytes())
    if change == "permission":
        data["license_notes"]["permission"] = "Private research only. Redistribution prohibited."
        source.write_text(json.dumps(data), encoding="utf-8")
    elif change == "terms":
        (checkout / "data/fixtures/README.md").write_text("Redistribution prohibited.")
    else:
        data["exits"] = data["exits"][:1]
        source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ResearchError) as denied:
        create_fixture_bundle(store, repository=checkout)
    assert denied.value.code == "BUNDLE_SOURCE"


def test_rehashed_terms_cannot_claim_original_permission(
    workspace: tuple[Path, LocalArtifactStore],
) -> None:
    """Verification must bind the authorized terms as well as the source and result."""
    checkout, store = workspace
    pointer = create_fixture_bundle(store, repository=checkout)
    forged = altered_component(store, pointer, "terms", b"No public use permitted.")
    with pytest.raises(ResearchError) as denied:
        verify_fixture_bundle(store, forged, repository=checkout)
    assert denied.value.code == "BUNDLE_SOURCE"


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"])
def test_powershell_bom_pointer_is_a_supported_cli_input(
    workspace: tuple[Path, LocalArtifactStore],
    capsys: pytest.CaptureFixture[str],
    encoding: str,
) -> None:
    """PowerShell's saved JSON encoding changes the pointer envelope, not artifact identity."""
    checkout, store = workspace
    pointer = create_fixture_bundle(store, repository=checkout)
    path = checkout.parent / "pointer.json"
    path.write_text(pointer.model_dump_json(), encoding=encoding)
    assert (
        main(
            [
                "verify-bundle",
                "--output",
                str(store.root),
                "--repository",
                str(checkout),
                "--ref",
                str(path),
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out)["universe"] == ["SEC-A", "SEC-B", "SEC-C"]


def test_invalid_bom_payload_has_safe_cli_failure(
    workspace: tuple[Path, LocalArtifactStore],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A truncated UTF-16 code unit must not leak a traceback or filesystem path."""
    checkout, store = workspace
    path = checkout.parent / "private-marker.json"
    path.write_bytes(b"\xff\xfe\x7b")
    assert (
        main(
            [
                "verify-bundle",
                "--output",
                str(store.root),
                "--repository",
                str(checkout),
                "--ref",
                str(path),
            ]
        )
        == 1
    )
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"]["code"] == "BUNDLE_INVALID"
    assert "private-marker" not in output.err


def initialize_repository(path: Path) -> None:
    """Create only a disposable local Git history with explicit fixture identity."""
    for arguments in [
        ("init",),
        ("add", "."),
        (
            "-c",
            "user.name=Fixture Review",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-m",
            "Original fixture review",
        ),
    ]:
        subprocess.run(
            ["git", "-C", str(path), *arguments], check=True, capture_output=True, timeout=20
        )


def test_clean_git_checkout_and_newline_only_replay(
    workspace: tuple[Path, LocalArtifactStore],
) -> None:
    """Actual clean Git provenance and canonical source identity survive a newline-only copy."""
    checkout, store = workspace
    initialize_repository(checkout)
    pointer = create_fixture_bundle(store, repository=checkout)
    graph = json.loads(store.get(pointer))
    git = json.loads(store.get(ArtifactRef.model_validate(graph["git"])))
    assert git["dirty"] is False and len(git["revision"]) == 40
    for relative in (*CODE_PATHS.values(), "uv.lock"):
        path = checkout / relative
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    result = verify_fixture_bundle(store, pointer, repository=checkout)
    facts = result["facts"]
    assert isinstance(facts, list)
    sources = []
    for row in facts:
        assert isinstance(row, dict)
        sources.append(row["source_id"])
    assert sources == [
        "filing-A-2022-original",
        "filing-A-2023-original",
        "filing-C-2023-original",
    ]
    source = store.get(ArtifactRef.model_validate(graph["input"]))
    assert source == (ROOT / FIXTURE_PATH).read_bytes()
    original = json.loads(source)
    assert len(original["facts"]) == 5 and len(original["exits"]) == 2
    assert original["exits"][1]["terminal_status"] == "unknown"
    assert original["exits"][1]["cash_per_share"] is None
    assert len(original["corporate_actions"]) == 2


def test_git_environment_cannot_relabel_requested_checkout(
    workspace: tuple[Path, LocalArtifactStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrelated inherited GIT_DIR must not supply a misleading revision for the source tree."""
    checkout, store = workspace
    initialize_repository(checkout)
    head = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    other = checkout.parent / "other"
    other.mkdir()
    (other / "unrelated.txt").write_text("different source tree")
    initialize_repository(other)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    pointer = create_fixture_bundle(store, repository=checkout)
    graph = json.loads(store.get(pointer))
    state = json.loads(store.get(ArtifactRef.model_validate(graph["git"])))
    assert state["revision"] == head and state["dirty"] is False


@pytest.mark.parametrize("failure", ["missing", "oversized", "not_utf8"])
def test_trusted_checkout_files_have_safe_read_boundaries(
    workspace: tuple[Path, LocalArtifactStore],
    failure: str,
) -> None:
    """Trusted code still needs bounded reads and safe missing/encoding failures."""
    checkout, store = workspace
    path = checkout / CODE_PATHS["point_in_time.py"]
    if failure == "missing":
        path.unlink()
    elif failure == "oversized":
        path.write_bytes(b"x" * (MAX_COMPONENT_BYTES + 1))
    else:
        path.write_bytes(b"\xff\xffnot-utf8")
    with pytest.raises(ResearchError) as invalid:
        create_fixture_bundle(store, repository=checkout)
    assert invalid.value.code == ("BUNDLE_CODE" if failure == "not_utf8" else "BUNDLE_INVALID")
    assert str(checkout) not in str(invalid.value)


def test_component_parser_enforces_its_own_byte_budget() -> None:
    """Direct parser callers retain a finite boundary independently of artifact retrieval."""
    with pytest.raises(ResearchError, match="byte limit"):
        parse_saved(b" " * (MAX_COMPONENT_BYTES + 1), FixtureBundle)


def test_code_inventory_omission_fails_before_replay(
    workspace: tuple[Path, LocalArtifactStore],
) -> None:
    """A smaller valid reference map cannot drop the source that interprets the fixture."""
    checkout, store = workspace
    pointer = create_fixture_bundle(store, repository=checkout)
    graph = json.loads(store.get(pointer))
    graph["code"].pop("point_in_time.py")
    changed = store.put(json.dumps(graph).encode(), media_type="application/json")
    with pytest.raises(ResearchError) as missing:
        verify_fixture_bundle(store, changed, repository=checkout)
    assert missing.value.code == "BUNDLE_CODE"


def test_parent_git_repository_does_not_become_checkout_provenance(
    workspace: tuple[Path, LocalArtifactStore],
) -> None:
    """A copied tree nested under an unrelated Git root keeps its own revision unknown."""
    checkout, store = workspace
    initialize_repository(checkout.parent)
    pointer = create_fixture_bundle(store, repository=checkout)
    graph = json.loads(store.get(pointer))
    state = json.loads(store.get(ArtifactRef.model_validate(graph["git"])))
    assert state == {"revision": None, "dirty": None}


def test_invalid_snapshot_clock_fails_with_safe_manifest_error(
    workspace: tuple[Path, LocalArtifactStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clock preceding fixture coverage cannot claim a valid acquisition timestamp."""

    class Clock:
        """Supply only the deliberately wrong snapshot time used by creation."""

        @classmethod
        def now(cls, tz: object = None) -> datetime:
            """Keep the failure independent of the machine's current date."""
            return datetime(2000, 1, 1, tzinfo=UTC)

    checkout, store = workspace
    monkeypatch.setattr("factorforge.data.fixture_bundle.datetime", Clock)
    with pytest.raises(ResearchError, match="manifest schema"):
        create_fixture_bundle(store, repository=checkout)
