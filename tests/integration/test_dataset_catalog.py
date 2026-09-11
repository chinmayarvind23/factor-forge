"""Catalog publication joins verified object bytes to owner-scoped PostgreSQL metadata."""

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.catalog import PostgresDatasetCatalog
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.datasets import DatasetManifest, DatasetObject, UsageRights
from factorforge.domain.errors import ResearchError
from factorforge.orchestration.postgres_runs import PostgresRunStore

INGESTOR = Principal(
    "fixture", "ingestor", frozenset({"ingest_dataset", "publish_dataset", "read_dataset"})
)
READER = Principal("fixture", "reader", frozenset({"read_dataset"}))


@pytest.fixture
def catalog() -> Iterator[PostgresDatasetCatalog]:
    """Use only an explicit isolated test database and an owned disposable object directory."""
    dsn = os.environ.get("FACTORFORGE_TEST_DSN")
    if not dsn:
        pytest.skip("Set FACTORFORGE_TEST_DSN to an isolated PostgreSQL test database")
    database = PostgresRunStore(dsn, schema="ff_test_" + uuid4().hex, require_test_database=True)
    try:
        with TemporaryDirectory(prefix="factorforge-catalog-") as directory:
            yield PostgresDatasetCatalog(database, LocalArtifactStore(Path(directory)))
    finally:
        database.close()


def dataset(artifact: ArtifactRef) -> DatasetManifest:
    """A project-original fixture has explicit reusable rights rather than inferred permission."""
    return DatasetManifest(
        name="catalog-fixture",
        kind="original_fixture",
        provider="FactorForge",
        source_version="v1",
        retrieved_at=datetime(2024, 5, 7, tzinfo=UTC),
        coverage_start=date(2024, 4, 29),
        coverage_end=date(2024, 5, 6),
        security_id_namespace="fixture-v1",
        universe_policy="fixture-membership-v1",
        availability_policy="known-by-formation-v1",
        corporate_action_policy="raw-events-v1",
        delisting_policy="require-terminal-outcome-v1",
        rights=UsageRights(
            provenance="Original constructed fixture.",
            permitted_uses=("local_research", "public_demo", "redistribution"),
        ),
        objects=(
            DatasetObject(name="facts", schema_version="facts-v1", row_count=1, artifact=artifact),
        ),
    )


def test_private_publication_is_idempotent_and_owner_scoped(
    catalog: PostgresDatasetCatalog,
) -> None:
    """A content digest alone never grants another user access to private input metadata."""
    manifest = dataset(catalog.objects.put(b'{"fixture":true}', media_type="application/json"))
    assert catalog.publish(manifest, INGESTOR) == manifest.version_id
    assert catalog.publish(manifest, INGESTOR) == manifest.version_id
    assert catalog.get(manifest.version_id, INGESTOR) == manifest
    with pytest.raises(ResearchError) as hidden:
        catalog.get(manifest.version_id, READER)
    assert hidden.value.code == "DATASET_NOT_FOUND"


def test_shared_dataset_requires_publication_capability(catalog: PostgresDatasetCatalog) -> None:
    """Ingestion permission cannot make a private dataset public through request metadata."""
    manifest = dataset(catalog.objects.put(b"shared-fixture"))
    private_ingestor = Principal("fixture", "restricted", frozenset({"ingest_dataset"}))
    with pytest.raises(ResearchError):
        catalog.publish(manifest, private_ingestor, shared=True)
    catalog.publish(manifest, INGESTOR, shared=True)
    assert catalog.get(manifest.version_id, READER) == manifest


def test_missing_object_and_failed_commit_do_not_publish(catalog: PostgresDatasetCatalog) -> None:
    """Orphaned bytes cannot make absent or uncommitted catalog metadata look complete."""
    missing = dataset(ArtifactRef(sha256="a" * 64, size_bytes=1, media_type="application/json"))
    with pytest.raises(ResearchError):
        catalog.publish(missing, INGESTOR)
    with pytest.raises(ResearchError):
        catalog.get(missing.version_id, INGESTOR)
    reference = catalog.objects.put(b"orphaned-once")
    manifest = dataset(reference)

    def fail() -> None:
        """Fail inside the actual publication transaction after its INSERT."""
        raise RuntimeError("simulated publication loss")

    catalog.before_commit = fail
    with pytest.raises(RuntimeError):
        catalog.publish(manifest, INGESTOR)
    assert catalog.objects.get(reference) == b"orphaned-once"
    with pytest.raises(ResearchError):
        catalog.get(manifest.version_id, INGESTOR)
    catalog.before_commit = None
    assert catalog.publish(manifest, INGESTOR) == manifest.version_id


@pytest.mark.parametrize("shared", [False, True])
def test_unknown_or_expired_rights_prevent_publication(
    catalog: PostgresDatasetCatalog,
    shared: bool,
) -> None:
    """Having an object and ingestion capability cannot override missing or expired rights."""
    original = dataset(catalog.objects.put(b"rights-boundary"))
    for rights in [
        UsageRights(provenance="Unverified rights grant nothing."),
        UsageRights(
            provenance="Expired provider permission.",
            permitted_uses=("local_research", "public_demo"),
            retention_expires_at=datetime(2000, 1, 1, tzinfo=UTC),
        ),
    ]:
        changed = DatasetManifest.model_validate({**original.model_dump(), "rights": rights})
        with pytest.raises(ResearchError, match="do not permit") as denied:
            catalog.publish(changed, INGESTOR, shared=shared)
        assert denied.value.code == "DATA_USE_DENIED"
        with pytest.raises(ResearchError) as absent:
            catalog.get(changed.version_id, INGESTOR)
        assert absent.value.code == "DATASET_NOT_FOUND"


def test_forged_manifest_has_safe_failure_without_publication(
    catalog: PostgresDatasetCatalog,
) -> None:
    """Validation-bypassing copies cannot publish or expose raw rejected metadata in errors."""
    original = dataset(catalog.objects.put(b"forged-input"))
    forged = original.model_copy(update={"provider": "private-input\x00content"})
    with pytest.raises(ResearchError) as invalid:
        catalog.publish(forged, INGESTOR)
    assert invalid.value.code == "DATASET_INVALID"
    assert "private-input" not in str(invalid.value)


def test_owner_namespace_capabilities_and_visibility_are_enforced(
    catalog: PostgresDatasetCatalog,
) -> None:
    """Same subject from another issuer cannot read or alter an existing private publication."""
    original = dataset(catalog.objects.put(b"owner-scoped"))
    other = Principal("other-issuer", INGESTOR.subject, INGESTOR.capabilities)
    catalog.publish(original, INGESTOR)
    with pytest.raises(ResearchError) as absent:
        catalog.get(original.version_id, other)
    assert absent.value.code == "DATASET_NOT_FOUND"
    with pytest.raises(ResearchError) as conflict:
        catalog.publish(original, INGESTOR, shared=True)
    assert conflict.value.code == "DATASET_CONFLICT"
    catalog.publish(original, other)
    assert catalog.get(original.version_id, other) == original
    forbidden = Principal("fixture", "none", frozenset())
    with pytest.raises(ResearchError) as denied:
        catalog.publish(original, forbidden)
    assert denied.value.code == "FORBIDDEN"
    with pytest.raises(ResearchError) as denied:
        catalog.get(original.version_id, forbidden)
    assert denied.value.code == "FORBIDDEN"
    with pytest.raises(ResearchError) as absent:
        catalog.get("../invalid", INGESTOR)
    assert absent.value.code == "DATASET_NOT_FOUND"


@pytest.mark.parametrize("mutation", ["invalid_schema", "changed_policy"])
def test_stored_metadata_corruption_fails_closed(
    catalog: PostgresDatasetCatalog,
    mutation: str,
) -> None:
    """Valid JSON in PostgreSQL is insufficient without schema and exact identity checks."""
    original = dataset(catalog.objects.put(b"metadata-corruption"))
    catalog.publish(original, INGESTOR)
    corrupted = original.model_dump(mode="json")
    corrupted["schema_version" if mutation == "invalid_schema" else "universe_policy"] = "altered"
    with catalog._database._connection() as connection:
        connection.execute(
            "UPDATE dataset_versions SET manifest=%s WHERE version_id=%s",
            (Jsonb(corrupted), original.version_id),
        )
    with pytest.raises(ResearchError) as invalid:
        catalog.get(original.version_id, INGESTOR)
    assert invalid.value.code == "DATASET_CORRUPT"


def test_objects_are_verified_again_when_reading(catalog: PostgresDatasetCatalog) -> None:
    """A committed manifest cannot conceal damaged or removed underlying bytes."""
    reference = catalog.objects.put(b"original-object")
    original = dataset(reference)
    catalog.publish(original, INGESTOR)
    assert isinstance(catalog.objects, LocalArtifactStore)
    # Locate only this fixture's exact digest under the test-owned object directory.
    paths = list(catalog.objects.root.rglob(reference.sha256))
    assert len(paths) == 1
    paths[0].write_bytes(b"corrupt-object")
    with pytest.raises(ResearchError) as invalid:
        catalog.get(original.version_id, INGESTOR)
    assert invalid.value.code == "ARTIFACT_INTEGRITY"


@pytest.mark.parametrize("operation", ["publish", "read"])
def test_expiry_during_object_verification_fails_closed(
    catalog: PostgresDatasetCatalog,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """Slow object verification cannot publish or return data after retention expires."""

    class Clock:
        """Advance only the catalog clock, preserving deterministic provider timing."""

        current = datetime(2029, 12, 31, tzinfo=UTC)

        @classmethod
        def now(cls, tz: object = None) -> datetime:
            """Return the explicit test instant without changing unrelated runtime clocks."""
            return cls.current

    monkeypatch.setattr("factorforge.data.catalog.datetime", Clock)
    original = dataset(catalog.objects.put(b"expires-during-read"))
    rights = original.rights.model_copy(
        update={"retention_expires_at": datetime(2030, 1, 1, tzinfo=UTC)}
    )
    changed = DatasetManifest.model_validate({**original.model_dump(), "rights": rights})
    if operation == "read":
        catalog.publish(changed, INGESTOR)
    real_get = catalog.objects.get

    def advance(ref: ArtifactRef) -> bytes:
        """Complete a verified object read exactly when the allowed retention expires."""
        result = real_get(ref)
        Clock.current = datetime(2030, 1, 1, tzinfo=UTC)
        return result

    monkeypatch.setattr(catalog.objects, "get", advance)
    with pytest.raises(ResearchError) as expired:
        if operation == "publish":
            catalog.publish(changed, INGESTOR)
        else:
            catalog.get(changed.version_id, INGESTOR)
    assert expired.value.code == "DATA_USE_DENIED"
    with pytest.raises(ResearchError) as absent:
        catalog.get(changed.version_id, INGESTOR)
    assert absent.value.code == (
        "DATASET_NOT_FOUND" if operation == "publish" else "DATA_USE_DENIED"
    )


def test_concurrent_replays_commit_one_owner_version(catalog: PostgresDatasetCatalog) -> None:
    """Concurrent PostgreSQL inserts arbitrate one immutable receipt for the same owner."""
    original = dataset(catalog.objects.put(b"concurrent-publish"))
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(catalog.publish, original, INGESTOR) for _ in range(4)]
        assert [future.result() for future in futures] == [original.version_id] * 4
    with catalog._database._connection() as connection:
        count = connection.execute("SELECT count(*) AS total FROM dataset_versions").fetchone()
    assert count is not None and count["total"] == 1


def test_use_permission_is_rechecked_on_reads(catalog: PostgresDatasetCatalog) -> None:
    """Private research rights do not permit later redistribution of identical content."""
    original = dataset(catalog.objects.put(b"research-only"))
    data = original.model_dump()
    data["rights"]["permitted_uses"] = ("local_research",)
    restricted = DatasetManifest.model_validate(data)
    catalog.publish(restricted, INGESTOR)
    assert catalog.get(restricted.version_id, INGESTOR) == restricted
    with pytest.raises(ResearchError) as denied:
        catalog.get(restricted.version_id, INGESTOR, operation="redistribution")
    assert denied.value.code == "DATA_USE_DENIED"
