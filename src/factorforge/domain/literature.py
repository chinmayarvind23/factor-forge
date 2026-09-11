"""Immutable literature metadata separates source provenance from the actual indexed document."""

import hashlib
import json
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator

_HTTPS_URL = TypeAdapter(HttpUrl)


class PaperDocument(BaseModel):
    """Source text is untrusted data; metadata never grants network or tool permissions."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, revalidate_instances="always"
    )
    paper_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(max_length=16000)
    source_url: str = Field(min_length=9, max_length=2048)
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    content_kind: Literal["original_summary", "source_passage"]
    source_version: str = Field(min_length=1, max_length=200)

    @field_validator("paper_id", "title", "text", "source_version", "source_url")
    @classmethod
    def portable_text(cls, value: str) -> str:
        """Reject control characters after Unicode validation; preserve passage line breaks."""
        if any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in value):
            raise ValueError("Literature text contains unsupported control characters")
        return value

    @field_validator("title", "source_version")
    @classmethod
    def meaningful_label(cls, value: str) -> str:
        """Whitespace-only labels cannot provide a usable title or source revision."""
        if not value.strip():
            raise ValueError("Literature labels cannot be blank")
        return value

    @field_validator("source_url")
    @classmethod
    def source_locator(cls, value: str) -> str:
        """Require HTTPS without credentials, fragments, whitespace or ambiguous backslashes."""
        if not value.startswith("https://") or "#" in value or "\\" in value:
            raise ValueError("Source URL must be an HTTPS locator without fragments")
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Source URL contains whitespace or control characters")
        authority = urlsplit(value).netloc
        if not authority or "@" in authority:
            raise ValueError(
                "Source URL requires an unambiguous authority without user information"
            )
        _HTTPS_URL.validate_python(value)
        return value

    def canonical_bytes(self) -> bytes:
        """Bind all declared document content/provenance with sorted compact UTF-8 JSON."""
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    @property
    def content_sha256(self) -> str:
        """Identify this document record separately from the optional upstream-source hash."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class LexicalHit(BaseModel):
    """A ranked hit retains the validated document identity and a usable finite positive score."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, revalidate_instances="always"
    )
    document: PaperDocument
    score: float = Field(gt=0, allow_inf_nan=False)
