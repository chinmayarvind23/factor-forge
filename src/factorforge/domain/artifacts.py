"""Portable content identities cannot carry caller-selected filesystem or cloud locations."""

from pydantic import BaseModel, ConfigDict, Field

MAX_ARTIFACT_BYTES = 2**30


class ArtifactRef(BaseModel):
    """Exact bytes determine identity; media type describes trusted ingestion's interpretation."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, revalidate_instances="always"
    )
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0, le=MAX_ARTIFACT_BYTES)
    media_type: str = Field(
        min_length=3,
        max_length=127,
        pattern=r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$",
    )
