"""Publish verified immutable dataset metadata in the existing canonical PostgreSQL boundary."""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from psycopg.types.json import Jsonb
from pydantic import ValidationError

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.datasets import DatasetManifest, PermittedUse
from factorforge.domain.errors import ResearchError
from factorforge.orchestration.postgres_runs import PostgresRunStore


def require_use(manifest: DatasetManifest, operation: PermittedUse) -> None:
    """Recheck retention at admission and after dependency work before returning or committing."""
    if not manifest.rights.permits(operation, datetime.now(UTC)):
        raise ResearchError("DATA_USE_DENIED", "Dataset use rights do not permit this use.", 403)


class PostgresDatasetCatalog:
    """Object upload and catalog publication are separate; an orphaned object grants no access."""

    def __init__(self, database: PostgresRunStore, objects: ArtifactStore) -> None:
        """Reuse the bounded canonical pool and its configured schema instead of another service."""
        self._database = database
        self.objects = objects
        self.before_commit: Callable[[], None] | None = None
        with self._database._connection() as connection, connection.transaction():
            migration = Path(__file__).with_name("migrations") / "001_dataset_versions.sql"
            connection.execute(migration.read_text(encoding="utf-8"), prepare=False)

    def publish(
        self, manifest: DatasetManifest, principal: Principal, *, shared: bool = False
    ) -> str:
        """Trusted ingestion verifies rights and every referenced object before catalog commit."""
        principal.require("ingest_dataset")
        if shared:
            principal.require("publish_dataset")
        try:
            validated = DatasetManifest.model_validate(manifest)
        except ValidationError:
            raise ResearchError(
                "DATASET_INVALID", "The dataset metadata is invalid.", 422
            ) from None
        now = datetime.now(UTC)
        required: PermittedUse = "public_demo" if shared else "local_research"
        require_use(validated, required)
        for item in validated.objects:
            self.objects.get(item.artifact)
        version_id = validated.version_id
        with self._database._connection() as connection, connection.transaction():
            connection.execute(
                "INSERT INTO dataset_versions VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (owner_issuer,owner_subject,version_id) DO NOTHING",
                (
                    principal.issuer,
                    principal.subject,
                    version_id,
                    Jsonb(validated.model_dump(mode="json")),
                    shared,
                    now,
                ),
            )
            saved = connection.execute(
                "SELECT manifest,shared FROM dataset_versions WHERE owner_issuer=%s "
                "AND owner_subject=%s AND version_id=%s FOR UPDATE",
                (principal.issuer, principal.subject, version_id),
            ).fetchone()
            if (
                saved is None
                or saved["manifest"] != validated.model_dump(mode="json")
                or saved["shared"] != shared
            ):
                raise ResearchError("DATASET_CONFLICT", "Dataset publication already differs.", 409)
            if self.before_commit is not None:
                self.before_commit()
            require_use(validated, required)
        return version_id

    def get(
        self,
        version_id: str,
        principal: Principal,
        *,
        operation: PermittedUse = "local_research",
    ) -> DatasetManifest:
        """A digest is an identity, not authorization; reads recheck retention and exact bytes."""
        principal.require("read_dataset")
        if not re.fullmatch(r"[a-f0-9]{64}", version_id):
            raise ResearchError(
                "DATASET_NOT_FOUND", "No accessible dataset has that identity.", 404
            )
        with self._database._connection() as connection:
            saved = connection.execute(
                "SELECT manifest FROM dataset_versions WHERE version_id=%s AND "
                "((owner_issuer=%s AND owner_subject=%s) OR shared) LIMIT 1",
                (version_id, principal.issuer, principal.subject),
            ).fetchone()
        if saved is None:
            raise ResearchError(
                "DATASET_NOT_FOUND", "No accessible dataset has that identity.", 404
            )
        try:
            manifest = DatasetManifest.model_validate(saved["manifest"])
        except ValidationError:
            raise ResearchError(
                "DATASET_CORRUPT", "The dataset metadata cannot be verified.", 409
            ) from None
        if manifest.version_id != version_id:
            raise ResearchError("DATASET_CORRUPT", "The dataset identity no longer matches.", 409)
        require_use(manifest, operation)
        for item in manifest.objects:
            self.objects.get(item.artifact)
        require_use(manifest, operation)
        return manifest
