"""Explicit protobuf presence and bounded messages precede strict application validation."""

from uuid import UUID

from google.protobuf.message import Message

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.interop.lean import lean_pb2 as pb
from factorforge.interop.lean.contract import VerificationRequest

MAX_MESSAGE_BYTES = 65536
WIRE_VERSION = "factorforge-lean-rpc-v1"


def require_message(message: Message, fields: tuple[str, ...]) -> None:
    """Reject excessive or unknown wire data before optional fields become application defaults."""
    if message.ByteSize() > MAX_MESSAGE_BYTES or any(not message.HasField(name) for name in fields):
        raise ValueError("Required bounded protobuf fields are absent")
    clean = type(message)()
    clean.CopyFrom(message)
    clean.DiscardUnknownFields()
    if clean.SerializeToString(deterministic=True) != message.SerializeToString(deterministic=True):
        raise ValueError("Unknown protobuf fields are unsupported")


def artifact_from_wire(message: pb.ArtifactReference) -> ArtifactRef:
    """A reference must explicitly supply its digest, size and interpretation."""
    require_message(message, ("sha256", "size_bytes", "media_type"))
    return ArtifactRef(
        sha256=message.sha256, size_bytes=message.size_bytes, media_type=message.media_type
    )


def artifact_to_wire(ref: ArtifactRef) -> pb.ArtifactReference:
    """Revalidate copied content identities before producing a wire reference."""
    value = ArtifactRef.model_validate(ref)
    return pb.ArtifactReference(
        sha256=value.sha256, size_bytes=value.size_bytes, media_type=value.media_type
    )


def decode_request(message: pb.VerifyStrategyRequest) -> VerificationRequest:
    """Unknown enums and missing fields fail without exposing raw request contents."""
    try:
        require_message(
            message,
            (
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
            ),
        )
        if message.comparison != pb.COMPARISON_EXACT_NAV:
            raise ValueError("Unknown comparison policy")
        return VerificationRequest(
            schema_version=message.schema_version,  # type: ignore[arg-type]
            verification_id=UUID(message.verification_id),
            run_id=UUID(message.run_id),
            owner_issuer=message.owner_issuer,
            owner_subject=message.owner_subject,
            factor_spec_sha256=message.factor_spec_sha256,
            profile=message.profile,
            source=artifact_from_wire(message.source),
            reference=artifact_from_wire(message.reference),
            comparison="exact_nav",
        )
    except (ValueError, TypeError, RecursionError):
        raise ResearchError(
            "LEAN_REQUEST_INVALID", "Verification request is invalid.", 422
        ) from None


def encode_request(request: VerificationRequest) -> pb.VerifyStrategyRequest:
    """Portable UUID strings retain the validated request's exact owner and artifact closure."""
    value = VerificationRequest.model_validate(request)
    message = pb.VerifyStrategyRequest(
        schema_version=value.schema_version,
        verification_id=str(value.verification_id),
        run_id=str(value.run_id),
        owner_issuer=value.owner_issuer,
        owner_subject=value.owner_subject,
        factor_spec_sha256=value.factor_spec_sha256,
        profile=value.profile,
        source=artifact_to_wire(value.source),
        reference=artifact_to_wire(value.reference),
        comparison=pb.COMPARISON_EXACT_NAV,
    )
    if message.ByteSize() > MAX_MESSAGE_BYTES:
        raise ResearchError(
            "LEAN_REQUEST_INVALID", "Verification request exceeds wire bounds.", 422
        )
    return message
