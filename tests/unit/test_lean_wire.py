"""Real generated protobuf messages exercise explicit presence and exact economic text."""

from uuid import UUID

import pytest
from test_experiments import ref

from factorforge.domain.errors import ResearchError
from factorforge.interop.lean import lean_pb2 as pb
from factorforge.interop.lean.contract import VerificationRequest
from factorforge.interop.lean.wire import decode_request, encode_request


def request() -> VerificationRequest:
    """Content references and owner identify a conditional comparison without choosing code."""
    return VerificationRequest(
        schema_version="lean-verification-request-v1",
        verification_id=UUID(int=1),
        run_id=UUID(int=2),
        owner_issuer="local",
        owner_subject="owner",
        factor_spec_sha256="a" * 64,
        profile="lean-price-only-seeded-holdings-v1",
        source=ref(b"source"),
        reference=ref(b"reference"),
        comparison="exact_nav",
    )


def test_generated_wire_roundtrip_preserves_exact_identities() -> None:
    """The compiled protocol can round-trip all required fields without JSON coercion."""
    encoded = encode_request(request())
    restored = pb.VerifyStrategyRequest.FromString(encoded.SerializeToString())
    assert decode_request(restored) == request()


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "verification_id",
        "run_id",
        "owner_issuer",
        "owner_subject",
        "factor_spec_sha256",
        "profile",
        "source",
        "reference",
        "comparison",
    ],
)
def test_absent_required_proto_fields_do_not_become_defaults(field: str) -> None:
    """Explicit protobuf presence is checked before converting into an application request."""
    encoded = encode_request(request())
    encoded.ClearField(field)
    with pytest.raises(ResearchError):
        decode_request(encoded)


@pytest.mark.parametrize("value", [0, 999])
def test_unspecified_and_unknown_comparison_enums_fail(value: int) -> None:
    """Proto3 permits unknown numeric enums, but this execution boundary does not."""
    encoded = encode_request(request())
    encoded.comparison = value  # type: ignore[assignment]
    with pytest.raises(ResearchError):
        decode_request(encoded)


def test_unknown_proto_fields_and_large_messages_fail() -> None:
    """Unrecognized wire members cannot hide ignored policy requests or exceed parser bounds."""
    encoded = encode_request(request())
    encoded.ParseFromString(encoded.SerializeToString() + b"\xa0\x06\x01")
    with pytest.raises(ResearchError):
        decode_request(encoded)
    encoded = encode_request(request())
    encoded.profile = "x" * 65537
    with pytest.raises(ResearchError):
        decode_request(encoded)


def test_nested_artifact_presence_is_required() -> None:
    """A missing uint64 byte count must not be interpreted as a valid zero-length artifact."""
    encoded = encode_request(request())
    encoded.source.ClearField("size_bytes")
    with pytest.raises(ResearchError):
        decode_request(encoded)


@pytest.mark.parametrize(
    "size,media", [(0, "application/json"), (2**20 + 1, "application/json"), (1, "text/plain")]
)
def test_source_reference_has_bounded_explicit_json_interpretation(size: int, media: str) -> None:
    """Metadata rejects unsupported source sizes or media before any storage allocation."""
    encoded = encode_request(request())
    encoded.source.size_bytes = size
    encoded.source.media_type = media
    with pytest.raises(ResearchError):
        decode_request(encoded)
