"""Dataset identities bind provenance and timing policy, not only raw file bytes."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.datasets import DatasetManifest, DatasetObject, DvcReference, UsageRights


def manifest() -> DatasetManifest:
    """The fixture provenance is explicit and carries no empirical-replication label."""
    return DatasetManifest(
        name="tiny-market-v1",
        kind="original_fixture",
        provider="FactorForge",
        source_version="fixture-v1",
        retrieved_at=datetime(2024, 5, 7, tzinfo=UTC),
        coverage_start=date(2024, 4, 29),
        coverage_end=date(2024, 5, 6),
        security_id_namespace="fixture-security-v1",
        universe_policy="fixture-membership-v1",
        availability_policy="known-by-formation-v1",
        corporate_action_policy="raw-events-v1",
        delisting_policy="require-terminal-outcome-v1",
        rights=UsageRights(
            provenance="Original constructed fixture, no third-party observations.",
            permitted_uses=("local_research", "public_demo", "redistribution"),
        ),
        objects=(
            DatasetObject(
                name="market",
                row_count=18,
                schema_version="fixture-v1",
                artifact=ArtifactRef(
                    sha256="a" * 64, size_bytes=123, media_type="application/json"
                ),
            ),
        ),
    )


def test_version_identity_covers_metadata_and_bytes() -> None:
    """Changing timing policy or an input object always creates a distinct dataset identity."""
    original = manifest()
    restored = DatasetManifest.model_validate_json(original.canonical_bytes())
    assert restored.version_id == original.version_id
    assert len(original.version_id) == 64
    changed = DatasetManifest.model_validate(
        {**original.model_dump(), "availability_policy": "lagged-v2"}
    )
    assert changed.version_id != original.version_id


def test_order_is_canonical_and_duplicates_fail() -> None:
    """Input ordering cannot create a new snapshot; duplicate table names are ambiguous."""
    original = manifest()
    second = DatasetObject(
        name="facts",
        row_count=2,
        schema_version="facts-v1",
        artifact=ArtifactRef(sha256="b" * 64, size_bytes=30, media_type="application/json"),
    )
    fields = original.model_dump()
    first = DatasetManifest.model_validate({**fields, "objects": (*original.objects, second)})
    reordered = DatasetManifest.model_validate({**fields, "objects": (second, *original.objects)})
    assert first.version_id == reordered.version_id
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(
            {**fields, "objects": (*original.objects, *original.objects)}
        )


def test_rights_and_time_constraints_are_explicit() -> None:
    """Unknown permissions cannot imply public release, and inconsistent coverage is rejected."""
    rights = UsageRights(provenance="Provider terms not yet verified.")
    assert not rights.permits("redistribution", datetime(2024, 1, 1, tzinfo=UTC))
    original = manifest()
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate({**original.model_dump(), "coverage_end": date(2020, 1, 1)})
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(
            {**original.model_dump(), "retrieved_at": datetime(2024, 5, 7)}
        )


@pytest.mark.parametrize("text", ["   ", "\t\n ", "source\x00text", "source\ud800text"])
def test_provenance_requires_printable_meaningful_text(text: str) -> None:
    """Declared permission must retain usable evidence and safe canonical UTF-8 metadata."""
    with pytest.raises(ValidationError):
        UsageRights(provenance=text, permitted_uses=("redistribution",))


@pytest.mark.parametrize("field", ["provider", "terms_reference"])
def test_descriptive_fields_reject_blank_or_control_metadata(field: str) -> None:
    """A present source label or terms reference cannot be empty explanatory metadata."""
    data = manifest().model_dump()
    if field == "provider":
        data[field] = " \t"
    else:
        data["rights"][field] = " \t"
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(data)


@pytest.mark.parametrize(
    "path",
    [
        "../x.dvc",
        "/x.dvc",
        "a//x.dvc",
        "C:/x.dvc",
        "a\\x.dvc",
        "a/./x.dvc",
        "x.txt",
        "a/\nx.dvc",
        "a/\tx.dvc",
        "a/%2e%2e/x.dvc",
        "a/space .dvc",
    ],
)
def test_dvc_pointer_is_a_portable_literal_repo_path(path: str) -> None:
    """Pointer paths cannot carry traversal, URL syntax, controls or ambiguous whitespace."""
    with pytest.raises(ValidationError):
        DvcReference(
            git_revision="a" * 40,
            pointer_path=path,
            tool_version="3.67.0",
            algorithm="md5",
            digest="b" * 32,
        )


def test_dvc_and_timezone_canonical_identity() -> None:
    """Native DVC digest, exact pointer and equivalent absolute instants bind one identity."""
    data = manifest().model_dump()
    data["dvc"] = DvcReference(
        git_revision="a" * 40,
        pointer_path="data/fixture.json.dvc",
        tool_version="3.67.0",
        algorithm="md5",
        digest="b" * 32 + ".dir",
    )
    original = DatasetManifest.model_validate(data)
    assert original.dvc is not None and original.dvc.digest.endswith(".dir")
    data["retrieved_at"] = datetime(2024, 5, 6, 19, tzinfo=timezone(timedelta(hours=-5)))
    assert DatasetManifest.model_validate(data).version_id == original.version_id
    data["dvc"] = {**original.dvc.model_dump(), "digest": "c" * 32}
    assert DatasetManifest.model_validate(data).version_id != original.version_id


def test_retention_deadline_is_exclusive_and_timezone_aware() -> None:
    """Known rights stop exactly at expiry; unknown rights and naive clocks grant nothing."""
    expiry = datetime(2030, 1, 1, tzinfo=UTC)
    rights = UsageRights(
        provenance="Explicit original fixture permission.",
        permitted_uses=("public_demo", "local_research", "public_demo"),
        retention_expires_at=expiry.astimezone(timezone(timedelta(hours=3))),
    )
    assert rights.permitted_uses == ("local_research", "public_demo")
    assert rights.retention_expires_at == expiry
    assert rights.permits("public_demo", expiry - timedelta(microseconds=1))
    assert not rights.permits("public_demo", expiry)
    assert not rights.permits("public_demo", datetime(2029, 1, 1))
    assert not rights.permits("redistribution", expiry - timedelta(seconds=1))


def test_total_object_size_and_future_coverage_fail() -> None:
    """Individually valid objects cannot exceed the dataset allocation bound in aggregate."""
    data = manifest().model_dump()
    first = {
        **data["objects"][0],
        "artifact": {
            "sha256": "a" * 64,
            "size_bytes": 300 * 2**20,
            "media_type": "application/json",
        },
    }
    data["objects"] = (first, {**first, "name": "other"})
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(data)
    data = manifest().model_dump()
    data["coverage_end"] = date(2025, 1, 1)
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(data)


def test_forged_nested_models_are_revalidated() -> None:
    """Bypassing construction on a nested object cannot bypass manifest validation."""
    original = manifest()
    forged = original.objects[0].model_copy(update={"row_count": -1})
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(original.model_copy(update={"objects": (forged,)}))
    forged_ref = original.objects[0].artifact.model_copy(update={"sha256": "../escape"})
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(
            original.model_copy(
                update={
                    "objects": (original.objects[0].model_copy(update={"artifact": forged_ref}),)
                }
            )
        )
