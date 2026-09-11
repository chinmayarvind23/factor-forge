"""Real SDK request validation with controlled responses; these are not live AWS tests."""

import base64
import hashlib
from io import BytesIO
from typing import cast

import boto3  # type: ignore[import-untyped]
import pytest
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import (  # type: ignore[import-untyped]
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
)
from botocore.response import StreamingBody  # type: ignore[import-untyped]
from botocore.stub import Stubber  # type: ignore[import-untyped]

from factorforge.data.s3_artifacts import S3ArtifactStore, S3Transport
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError


def fixture() -> tuple[S3ArtifactStore, Stubber, ArtifactRef, dict[str, object]]:
    """Explicit fake credentials and Stubber prevent credential lookup and network access."""
    client = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="fixture", aws_secret_access_key="fixture"
    )
    ref = ArtifactRef(
        sha256=hashlib.sha256(b"abc").hexdigest(), size_bytes=3, media_type="text/plain"
    )
    request: dict[str, object] = {
        "Bucket": "factorforge-contract-tests",
        "Key": "fixtures/sha256/" + ref.sha256[:2] + "/" + ref.sha256,
    }
    return (
        S3ArtifactStore(
            cast(S3Transport, client), bucket="factorforge-contract-tests", prefix="fixtures"
        ),
        Stubber(client),
        ref,
        request,
    )


def response(data: bytes = b"abc") -> dict[str, object]:
    """StreamingBody exercises bounded reads and closure using the real botocore wrapper."""
    return {
        "Body": StreamingBody(BytesIO(data), len(data)),
        "ContentLength": len(data),
        "ChecksumSHA256": base64.b64encode(hashlib.sha256(data).digest()).decode(),
    }


@pytest.mark.parametrize("existing", [False, True])
def test_conditional_publication_verifies_exact_existing_or_created_bytes(existing: bool) -> None:
    """Every write is conditional and followed by verification, including concurrent replay."""
    store, stubber, ref, request = fixture()
    put = {
        **request,
        "Body": b"abc",
        "ContentType": "text/plain",
        "IfNoneMatch": "*",
        "ChecksumSHA256": base64.b64encode(bytes.fromhex(ref.sha256)).decode(),
    }
    if existing:
        stubber.add_client_error(
            "put_object", "PreconditionFailed", http_status_code=412, expected_params=put
        )
    else:
        stubber.add_response("put_object", {}, put)
    stubber.add_response("get_object", response(), {**request, "ChecksumMode": "ENABLED"})
    with stubber:
        assert store.put(b"abc", media_type="text/plain") == ref
    stubber.assert_no_pending_responses()


@pytest.mark.parametrize("data", [b"abd", b"a", b"abcd"])
def test_corrupt_remote_objects_fail_closed(data: bytes) -> None:
    """Neither metadata nor an ETag allows altered or truncated content to pass."""
    store, stubber, ref, request = fixture()
    stubber.add_response("get_object", response(data), {**request, "ChecksumMode": "ENABLED"})
    with stubber, pytest.raises(ResearchError) as failure:
        store.get(ref)
    assert failure.value.code == "ARTIFACT_INTEGRITY"


@pytest.mark.parametrize(
    "status,code", [(404, "ARTIFACT_MISSING"), (403, "ARTIFACT_IO"), (503, "ARTIFACT_IO")]
)
def test_provider_failures_are_bounded_and_sanitized(status: int, code: str) -> None:
    """Transient failures retry three times; unavailable/denied reads never leak SDK details."""
    store, stubber, ref, request = fixture()
    for _ in range(3 if status == 503 else 1):
        stubber.add_client_error(
            "get_object",
            "ProviderError",
            "sensitive provider detail",
            http_status_code=status,
            expected_params={**request, "ChecksumMode": "ENABLED"},
        )
    with stubber, pytest.raises(ResearchError) as failure:
        store.get(ref)
    assert failure.value.code == code
    assert "sensitive" not in str(failure.value)
    stubber.assert_no_pending_responses()


@pytest.mark.parametrize(
    "updates",
    [
        {"bucket": "https://untrusted.example"},
        {"prefix": "../other"},
        {"prefix": ""},
        {"max_attempts": 0},
        {"max_attempts": True},
        {"max_object_bytes": -1},
    ],
)
def test_configuration_rejects_unbounded_or_ambiguous_destinations(
    updates: dict[str, object],
) -> None:
    """Caller-shaped locators and disabled retry/byte limits cannot enter a configured adapter."""
    with pytest.raises(ValueError):
        S3ArtifactStore(
            cast(S3Transport, object()),
            **{  # type: ignore[arg-type]
                "bucket": "factorforge-contract-tests",
                "prefix": "fixtures",
                **updates,
            },
        )


def test_retryable_put_conflict_retries_without_overwrite() -> None:
    """S3's documented concurrent-delete conflict permits another conditional PutObject."""
    store, stubber, ref, request = fixture()
    put = {
        **request,
        "Body": b"abc",
        "ContentType": "text/plain",
        "IfNoneMatch": "*",
        "ChecksumSHA256": base64.b64encode(bytes.fromhex(ref.sha256)).decode(),
    }
    stubber.add_client_error(
        "put_object", "ConditionalRequestConflict", http_status_code=409, expected_params=put
    )
    stubber.add_response("put_object", {"ChecksumSHA256": put["ChecksumSHA256"]}, put)
    stubber.add_response("get_object", response(), {**request, "ChecksumMode": "ENABLED"})
    with stubber:
        assert store.put(b"abc", media_type="text/plain") == ref
    stubber.assert_no_pending_responses()


class ControlledTransport:
    """Fault injection complements SDK syntax checks with malformed or failing stream behavior."""

    def __init__(self, value: dict[str, object] | Exception) -> None:
        """Retain one explicit response/failure and observable call count."""
        self.value = value
        self.calls = 0

    def get_object(self, **kwargs: object) -> dict[str, object]:
        """Expose controlled faults without any network or credential access."""
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value

    def put_object(self, **kwargs: object) -> dict[str, object]:
        """The same deterministic response permits checksum-response fault injection."""
        return self.get_object(**kwargs)


def controlled(value: dict[str, object] | Exception) -> tuple[S3ArtifactStore, ControlledTransport]:
    """Construct the adapter only from trusted constant fixture destinations."""
    client = ControlledTransport(value)
    return S3ArtifactStore(client, bucket="factorforge-contract-tests", prefix="fixtures"), client


def test_sdk_transport_errors_are_safe_and_retry_bounded() -> None:
    """Network failures retry while credential failures fail immediately with safe messages."""
    _, _, ref, _ = fixture()
    for error, attempts in [
        (EndpointConnectionError(endpoint_url="sensitive"), 3),
        (NoCredentialsError(), 1),
    ]:
        store, transport = controlled(error)
        with pytest.raises(ResearchError) as failure:
            store.get(ref)
        assert failure.value.code == "ARTIFACT_IO"
        assert "sensitive" not in str(failure.value)
        assert transport.calls == attempts


def test_checksum_response_and_metadata_limits_fail_before_streaming() -> None:
    """An incorrect upload checksum and oversized declarations cannot be accepted."""
    store, _ = controlled({"ChecksumSHA256": "incorrect"})
    with pytest.raises(ResearchError) as failure:
        store.put(b"abc")
    assert failure.value.code == "ARTIFACT_INTEGRITY"
    ref = ArtifactRef(sha256="0" * 64, size_bytes=2**30, media_type="text/plain")
    with pytest.raises(ResearchError) as large:
        store.get(ref)
    assert large.value.code == "ARTIFACT_TOO_LARGE"
    store, _ = controlled({})
    with pytest.raises(ResearchError):
        store.get(ref.model_copy(update={"size_bytes": 0}))


class FaultyBody:
    """Observe cleanup and bounded requests when a provider stream violates its contract."""

    def __init__(self, value: object) -> None:
        """Configure one read result/failure and retain whether close was called."""
        self.value = value
        self.closed = False

    def read(self, amount: int) -> bytes:
        """A deliberately broken transport can return too many bytes or raise an SDK error."""
        if isinstance(self.value, Exception):
            raise self.value
        return cast(bytes, self.value)

    def close(self) -> None:
        """Record release even when metadata or content validation fails."""
        self.closed = True


@pytest.mark.parametrize(
    "value",
    [b"too many bytes", "not bytes", b"abd", b"", ReadTimeoutError(endpoint_url="sensitive")],
)
def test_invalid_and_failed_streams_close(value: object) -> None:
    """Actual read/hash limits protect against misleading metadata and preserve cleanup."""
    _, _, ref, _ = fixture()
    body = FaultyBody(value)
    store, _ = controlled({"Body": body, "ContentLength": 3})
    with pytest.raises(ResearchError):
        store.get(ref)
    assert body.closed


def test_read_deadline_closes_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """Progressing one byte at a time cannot keep an object read alive without a deadline."""
    _, _, ref, _ = fixture()
    body = FaultyBody(b"a")
    store, _ = controlled({"Body": body, "ContentLength": 3})
    moments = iter([0.0, 31.0])
    monkeypatch.setattr("factorforge.data.s3_artifacts.time.monotonic", lambda: next(moments))
    with pytest.raises(ResearchError) as failure:
        store.get(ref)
    assert failure.value.code == "ARTIFACT_IO"
    assert body.closed


def test_stream_cannot_exceed_declared_length() -> None:
    """A valid stream with lying ContentLength still stops after at most expected bytes plus one."""
    _, _, ref, _ = fixture()
    body = BytesIO(b"abcd")
    store, _ = controlled({"Body": body, "ContentLength": 3})
    with pytest.raises(ResearchError) as failure:
        store.get(ref)
    assert failure.value.code == "ARTIFACT_INTEGRITY"
    assert body.closed


def test_factory_configures_finite_sdk_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK retries cannot multiply the adapter's own bounded attempts."""
    from factorforge.data.s3_artifacts import configured_s3_client

    def client(service: str, **kwargs: object) -> S3Transport:
        """Inspect client options without permitting client creation or credential lookup."""
        assert service == "s3"
        config = cast(Config, kwargs["config"])
        assert config.connect_timeout == 3
        assert config.read_timeout == 5
        assert config.retries == {"total_max_attempts": 1}
        return ControlledTransport({})

    monkeypatch.setattr("factorforge.data.s3_artifacts.boto3.client", client)
    assert isinstance(configured_s3_client(region="us-east-1"), ControlledTransport)
