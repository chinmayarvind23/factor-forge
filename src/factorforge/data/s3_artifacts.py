"""Conditional S3 storage verifies content; contract tests do not prove live AWS access."""

import base64
import re
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from typing import Protocol, cast

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from factorforge.data.artifacts import (
    DEFAULT_OBJECT_LIMIT,
    READ_CHUNK,
    artifact_error,
    reference,
    validate_limit,
    verify_bytes,
)
from factorforge.domain.artifacts import ArtifactRef

RETRYABLE = (ConnectionClosedError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError)


class S3Transport(Protocol):
    """The adapter depends only on bounded single-object operations, never caller-selected URLs."""

    def put_object(self, **kwargs: object) -> Mapping[str, object]:
        """Create one object conditionally with a full-object SHA-256 checksum."""
        ...

    def get_object(self, **kwargs: object) -> Mapping[str, object]:
        """Read a checksum-enabled object response with a closeable bounded stream."""
        ...


class _Body(Protocol):
    """Only bounded streaming reads are required from the SDK response body."""

    def read(self, amount: int) -> bytes:
        """Return at most the requested bytes or signal a provider read failure."""
        ...

    def close(self) -> None:
        """Release the response connection on success and every failure path."""
        ...


def configured_s3_client(*, region: str) -> S3Transport:
    """Use the runtime credential chain with finite network timeouts and no nested retries."""
    return cast(
        S3Transport,
        boto3.client(
            "s3",
            region_name=region,
            config=Config(connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 1}),
        ),
    )


class S3ArtifactStore:
    """Bucket and prefix come from trusted deployment configuration; refs contain only digests."""

    def __init__(
        self,
        client: S3Transport,
        *,
        bucket: str,
        prefix: str,
        max_object_bytes: int = DEFAULT_OBJECT_LIMIT,
        max_attempts: int = 3,
    ) -> None:
        """Reject ambiguous destination syntax and unbounded resource/retry configuration."""
        validate_limit(max_object_bytes)
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
            raise ValueError("Artifact bucket must be a configured simple DNS bucket name")
        if len(prefix) > 256 or not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", prefix):
            raise ValueError("Artifact prefix must contain explicit safe path segments")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise ValueError("Artifact operations require one to three attempts")
        self.client = client
        self.bucket = bucket
        self.prefix = prefix
        self.max_object_bytes = max_object_bytes
        self.max_attempts = max_attempts

    def _request(self, ref: ArtifactRef) -> dict[str, object]:
        """Canonical digest-only keys cannot escape the configured prefix."""
        return {"Bucket": self.bucket, "Key": f"{self.prefix}/sha256/{ref.sha256[:2]}/{ref.sha256}"}

    def _call(
        self, operation: Callable[[], Mapping[str, object]], *, conditional: bool = False
    ) -> Mapping[str, object] | None:
        """Bound transient retries and sanitize provider errors before crossing the adapter."""
        for attempt in range(self.max_attempts):
            try:
                return operation()
            except ClientError as error:
                status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if conditional and status == 412:
                    return None
                if status == 404:
                    raise artifact_error(
                        "ARTIFACT_MISSING", "Artifact is unavailable.", 404
                    ) from None
                if status not in {409, 429, 500, 502, 503, 504}:
                    break
            except RETRYABLE:
                pass
            except BotoCoreError:
                break
            if attempt + 1 < self.max_attempts:
                time.sleep(0.05 * (attempt + 1))
        raise artifact_error("ARTIFACT_IO", "Artifact storage operation failed.", 503) from None

    def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Create without overwriting; every outcome requires a verified read."""
        ref = reference(data, media_type, self.max_object_bytes)
        checksum = base64.b64encode(bytes.fromhex(ref.sha256)).decode("ascii")
        response = self._call(
            lambda: self.client.put_object(
                **self._request(ref),
                Body=data,
                ContentType=media_type,
                IfNoneMatch="*",
                ChecksumSHA256=checksum,
            ),
            conditional=True,
        )
        if response is not None and response.get("ChecksumSHA256", checksum) != checksum:
            raise artifact_error("ARTIFACT_INTEGRITY", "Artifact checksum does not match.")
        self.get(ref)
        return ref

    def get(self, ref: ArtifactRef) -> bytes:
        """Bound metadata, bytes and read duration; verify content independently of ETags."""
        ref = ArtifactRef.model_validate(ref)
        if ref.size_bytes > self.max_object_bytes:
            raise artifact_error("ARTIFACT_TOO_LARGE", "Artifact exceeds the byte limit.", 413)
        response = self._call(
            lambda: self.client.get_object(**self._request(ref), ChecksumMode="ENABLED")
        )
        if response is None or not callable(getattr(response.get("Body"), "close", None)):
            raise artifact_error("ARTIFACT_INTEGRITY", "Artifact response is invalid.")
        body = cast(_Body, response["Body"])
        try:
            if not callable(getattr(body, "read", None)):
                raise artifact_error("ARTIFACT_INTEGRITY", "Artifact response is invalid.")
            length = response.get("ContentLength")
            if type(length) is not int or length != ref.size_bytes:
                raise artifact_error("ARTIFACT_INTEGRITY", "Artifact length does not match.")
            checksum = base64.b64encode(bytes.fromhex(ref.sha256)).decode("ascii")
            if response.get("ChecksumSHA256", checksum) != checksum:
                raise artifact_error("ARTIFACT_INTEGRITY", "Artifact checksum does not match.")
            deadline = time.monotonic() + 30
            data = bytearray()
            while len(data) <= ref.size_bytes:
                if time.monotonic() >= deadline:
                    raise artifact_error("ARTIFACT_IO", "Artifact read deadline exceeded.", 503)
                amount = min(READ_CHUNK, ref.size_bytes + 1 - len(data))
                chunk = body.read(amount)
                if time.monotonic() >= deadline:
                    raise artifact_error("ARTIFACT_IO", "Artifact read deadline exceeded.", 503)
                if not isinstance(chunk, bytes) or len(chunk) > amount:
                    raise artifact_error("ARTIFACT_INTEGRITY", "Artifact stream is invalid.")
                if not chunk:
                    break
                data.extend(chunk)
            exact = bytes(data)
            verify_bytes(exact, ref)
            return exact
        except (OSError, BotoCoreError):
            raise artifact_error("ARTIFACT_IO", "Artifact read failed.", 503) from None
        finally:
            with suppress(OSError, BotoCoreError):
                body.close()
