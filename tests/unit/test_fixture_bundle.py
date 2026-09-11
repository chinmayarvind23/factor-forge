"""A data-check bundle must replay from verified bytes and reject altered lineage."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.fixture_bundle import (
    CODE_PATHS,
    FIXTURE_PATH,
    MAX_COMPONENT_BYTES,
    FixtureResult,
    create_fixture_bundle,
    verify_fixture_bundle,
)
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError

REPOSITORY = Path(__file__).resolve().parents[2]


def copy_repository(destination: Path) -> Path:
    """Copy only trusted replay files so tests can remove or alter a private checkout safely."""
    for relative in (*CODE_PATHS.values(), FIXTURE_PATH, "uv.lock", "data/fixtures/README.md"):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, target)
    return destination


def replace_component(
    store: LocalArtifactStore, ref: ArtifactRef, name: str, data: bytes
) -> ArtifactRef:
    """Give altered content a valid digest so replay, rather than hashing alone, must reject it."""
    bundle = json.loads(store.get(ref))
    bundle[name] = store.put(data, media_type="application/json").model_dump()
    return store.put(json.dumps(bundle).encode(), media_type="application/json")


def test_fixture_bundle_replays_without_original_input_file() -> None:
    """Saved content alone supplies input; expected source IDs were derived by hand."""
    with TemporaryDirectory(prefix="factorforge-bundle-") as directory:
        root = Path(directory)
        repository = copy_repository(root / "checkout")
        store = LocalArtifactStore(root / "objects")
        ref = create_fixture_bundle(store, repository=repository)
        (repository / FIXTURE_PATH).unlink()
        (repository / "data/fixtures/README.md").unlink()
        result = verify_fixture_bundle(store, ref, repository=repository)
        assert result["tier"] == "original_fixture"
        assert result["universe"] == ["SEC-A", "SEC-B", "SEC-C"]
        selected = FixtureResult.model_validate_json(json.dumps(result))
        assert [row.source_id for row in selected.facts] == [
            "filing-A-2022-original",
            "filing-A-2023-original",
            "filing-C-2023-original",
        ]


def test_later_bundle_filters_exited_securities_and_uses_known_amendment() -> None:
    """Membership and publication timing apply together, without rewriting old snapshots."""
    with TemporaryDirectory(prefix="factorforge-bundle-") as directory:
        store = LocalArtifactStore(Path(directory))
        ref = create_fixture_bundle(
            store,
            repository=REPOSITORY,
            formation_at=datetime(2024, 5, 6, 20, tzinfo=UTC),
            trade_at=datetime(2024, 5, 7, 13, 30, tzinfo=UTC),
        )
        result = verify_fixture_bundle(store, ref, repository=REPOSITORY)
        assert result["universe"] == ["SEC-A"]
        selected = FixtureResult.model_validate_json(json.dumps(result))
        assert [row.source_id for row in selected.facts] == [
            "filing-A-2022-original",
            "filing-A-2023-amendment",
        ]


def test_tampered_result_and_changed_trusted_code_fail() -> None:
    """A new valid content hash cannot make fabricated output agree with trusted replay."""
    with TemporaryDirectory(prefix="factorforge-bundle-") as directory:
        store = LocalArtifactStore(Path(directory) / "objects")
        ref = create_fixture_bundle(store, repository=REPOSITORY)
        bundle = json.loads(store.get(ref))
        altered = store.put(b'{"tier":"original_fixture","universe":[],"facts":[]}')
        bundle["result"] = altered.model_dump()
        forged = store.put(json.dumps(bundle).encode(), media_type="application/json")
        with pytest.raises(ResearchError, match="reproduce"):
            verify_fixture_bundle(store, forged, repository=REPOSITORY)
        bundle["code"]["point_in_time.py"] = altered.model_dump()
        forged = store.put(json.dumps(bundle).encode(), media_type="application/json")
        with pytest.raises(ResearchError, match="code"):
            verify_fixture_bundle(store, forged, repository=REPOSITORY)


def test_preserves_all_original_input_and_actual_environment_metadata() -> None:
    """Unused exits and actions remain exact bytes; missing Git metadata is never fabricated."""
    with TemporaryDirectory(prefix="factorforge-bundle-") as directory:
        root = Path(directory)
        repository = copy_repository(root / "checkout")
        store = LocalArtifactStore(root / "objects")
        ref = create_fixture_bundle(store, repository=repository)
        bundle = json.loads(store.get(ref))
        original = store.get(ArtifactRef(**bundle["input"]))
        assert original == (REPOSITORY / FIXTURE_PATH).read_bytes()
        assert json.loads(original)["exits"][1]["cash_per_share"] is None
        manifest = json.loads(store.get(ArtifactRef(**bundle["manifest"])))
        assert manifest["kind"] == "original_fixture"
        assert manifest["objects"][0]["row_count"] == 31
        assert manifest["coverage_start"] == "2024-04-29"
        assert manifest["coverage_end"] == "2024-05-06"
        assert manifest["dvc"] is None
        assert json.loads(store.get(ArtifactRef(**bundle["git"]))) == {
            "revision": None,
            "dirty": None,
        }


@pytest.mark.parametrize("component", ["input", "manifest", "terms", "lock", "environment", "git"])
def test_missing_component_prevents_verified_replay(component: str) -> None:
    """Every declared input and provenance component is required, including uninterpreted terms."""
    with TemporaryDirectory(prefix="factorforge-bundle-") as directory:
        store = LocalArtifactStore(Path(directory))
        ref = create_fixture_bundle(store, repository=REPOSITORY)
        bundle = json.loads(store.get(ref))
        digest = bundle[component]["sha256"]
        (store.root / "sha256" / digest[:2] / digest).unlink()
        with pytest.raises(ResearchError) as failure:
            verify_fixture_bundle(store, ref, repository=REPOSITORY)
        assert failure.value.code == "ARTIFACT_MISSING"


def test_invalid_timing_and_strict_input_fail_before_publishing() -> None:
    """Invalid causal timing and coerced membership must never produce a successful bundle."""
    with TemporaryDirectory(prefix="factorforge-bundle-") as directory:
        root = Path(directory)
        repository = copy_repository(root / "checkout")
        store = LocalArtifactStore(root / "objects")
        with pytest.raises(ResearchError) as failure:
            create_fixture_bundle(
                store,
                repository=repository,
                formation_at=datetime(2024, 5, 1, 20),
                trade_at=datetime(2024, 5, 1, 20),
            )
        assert failure.value.code == "TIMING_INVALID"
        source = json.loads((repository / FIXTURE_PATH).read_bytes())
        source["membership"][0]["included"] = "true"
        (repository / FIXTURE_PATH).write_text(json.dumps(source))
        with pytest.raises(ResearchError, match="schema"):
            create_fixture_bundle(store, repository=repository)
        assert not list(store.root.rglob("sha256"))


@pytest.mark.parametrize("component", ["config", "environment", "manifest"])
def test_valid_hash_metadata_changes_are_not_silently_accepted(component: str) -> None:
    """Typed metadata must agree with causal replay and the installed execution environment."""
    with TemporaryDirectory(prefix="factorforge-bundle-") as directory:
        store = LocalArtifactStore(Path(directory))
        ref = create_fixture_bundle(store, repository=REPOSITORY)
        bundle = json.loads(store.get(ref))
        value = json.loads(store.get(ArtifactRef(**bundle[component])))
        if component == "config":
            value["trade_at"] = value["formation_at"]
        elif component == "environment":
            value["python"] = "0.0.0"
        else:
            value["objects"][0]["row_count"] = 0
        forged = replace_component(store, ref, component, json.dumps(value).encode())
        with pytest.raises(ResearchError):
            verify_fixture_bundle(store, forged, repository=REPOSITORY)


@pytest.mark.parametrize(
    "data",
    [
        b'{"tier":"original_fixture","tier":"observed"}',
        b'{"value":NaN}',
        b"[" * 40 + b"0" + b"]" * 40,
        b" " * (MAX_COMPONENT_BYTES + 1),
    ],
    ids=["duplicate-key", "nonfinite", "deep", "oversized"],
)
def test_ambiguous_deep_and_oversized_json_is_rejected(data: bytes) -> None:
    """A finite strict JSON boundary applies before resolving any untrusted graph references."""
    with TemporaryDirectory(prefix="factorforge-bundle-") as directory:
        store = LocalArtifactStore(Path(directory))
        ref = store.put(data)
        with pytest.raises(ResearchError):
            verify_fixture_bundle(store, ref, repository=REPOSITORY)


def test_changed_checkout_code_and_lock_reject_saved_bundle() -> None:
    """A copied checkout cannot claim to be the trusted installed code after a local edit."""
    with TemporaryDirectory(prefix="factorforge-bundle-") as directory:
        root = Path(directory)
        repository = copy_repository(root / "checkout")
        store = LocalArtifactStore(root / "objects")
        ref = create_fixture_bundle(store, repository=repository)
        lock = repository / "uv.lock"
        lock.write_bytes(lock.read_bytes() + b"\n# changed")
        with pytest.raises(ResearchError, match="lock"):
            verify_fixture_bundle(store, ref, repository=repository)
        code = repository / CODE_PATHS["point_in_time.py"]
        code.write_bytes(code.read_bytes() + b"\n# changed")
        with pytest.raises(ResearchError, match="code"):
            verify_fixture_bundle(store, ref, repository=repository)


def test_code_newline_conversion_preserves_explicit_canonical_identity() -> None:
    """CRLF and LF checkouts share declared UTF-8/LF code hashes while input stays byte-exact."""
    with TemporaryDirectory(prefix="factorforge-bundle-") as directory:
        root = Path(directory)
        repository = copy_repository(root / "checkout")
        for relative in (*CODE_PATHS.values(), "uv.lock"):
            path = repository / relative
            data = path.read_bytes().replace(b"\r\n", b"\n")
            path.write_bytes(data.replace(b"\n", b"\r\n"))
        store = LocalArtifactStore(root / "objects")
        ref = create_fixture_bundle(store, repository=repository)
        bundle = json.loads(store.get(ref))
        assert bundle["text_identity"] == "utf8-lf-v1"
        assert b"\r" not in store.get(ArtifactRef(**bundle["code"]["point_in_time.py"]))
        for relative in (*CODE_PATHS.values(), "uv.lock"):
            path = repository / relative
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
        assert (
            verify_fixture_bundle(store, ref, repository=repository)["tier"] == "original_fixture"
        )
