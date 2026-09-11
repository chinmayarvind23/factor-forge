"""Cooperative gRPC boundary; no listener or engine exists until a trusted backend is supplied."""

import hashlib
import json
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event, Lock
from typing import Annotated, Literal, NoReturn, Protocol, Self

import grpc
from google.protobuf.message import Message
from pydantic import Field, model_validator

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Digest
from factorforge.interop.lean import lean_pb2 as pb
from factorforge.interop.lean import lean_pb2_grpc as rpc
from factorforge.interop.lean.contract import (
    PROFILE,
    NavPoint,
    NavReference,
    PriceOnlySource,
    UtcText,
    VerificationRequest,
)
from factorforge.interop.lean.wire import (
    MAX_MESSAGE_BYTES,
    WIRE_VERSION,
    artifact_to_wire,
    decode_request,
    require_message,
)
from factorforge.sandbox.policy import _principal

LEAN_COMMIT = "8ee075a39918f2df6fe9e0a5944e366fb60d10dc"
MAX_DEADLINE_SECONDS = 120
# A future host must apply these before protobuf deserialization allocates a message.
SERVER_OPTIONS = (
    ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
    ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
)


class RpcContext(Protocol):
    """Only authenticated hosting, cancellation and deadline operations cross this adapter."""

    def time_remaining(self) -> float | None:
        """Expose the transport's client deadline, with None meaning unbounded."""
        ...

    def is_active(self) -> bool:
        """Report whether the transport still accepts an operation result."""
        ...

    def add_callback(self, callback: Callable[[], None]) -> bool:
        """Arrange cooperative cancellation when the transport terminates."""
        ...

    def abort(self, code: grpc.StatusCode, details: str) -> NoReturn:
        """Terminate a transport error using only a safe fixed diagnostic."""
        ...


class EngineIdentity(Contract):
    """Trusted backend configuration identifies the pinned engine and server translator."""

    lean_commit: Literal["8ee075a39918f2df6fe9e0a5944e366fb60d10dc"] = (
        "8ee075a39918f2df6fe9e0a5944e366fb60d10dc"
    )
    profile: Literal["lean-price-only-seeded-holdings-v1"] = "lean-price-only-seeded-holdings-v1"
    image_sha256: Digest
    translator_sha256: Digest


class EngineRun(Contract):
    """Backend output is bounded and retained; typed coherence is not engine attestation."""

    identity: EngineIdentity
    points: Annotated[tuple[NavPoint, ...], Field(min_length=1, max_length=128)]
    raw_output: Annotated[bytes, Field(min_length=1, max_length=2**20)]
    cleanup_confirmed: bool

    @model_validator(mode="after")
    def ordered_points(self) -> Self:
        """Returned observation clocks cannot silently overwrite duplicate engine rows."""
        NavReference(
            schema_version="lean-nav-reference-v1", source_sha256="0" * 64, points=self.points
        )
        return self


class EngineBackend(Protocol):
    """A trusted adapter owns actual image checks, output parsing and cooperative teardown."""

    def ready(self) -> EngineIdentity | None:
        """Return current runtime identity only when the actual engine is available."""
        ...

    def execute(self, source: PriceOnlySource, *, cancelled: Event, deadline: float) -> EngineRun:
        """Run fixed translation from source alone; never accept expected comparison values.

        Deadline is an absolute monotonic instant. Observe cancellation/deadline during work
        and finish resource cleanup before returning; the handler retains admission until then.
        """
        ...


class VerificationRecord(Contract):
    """An immutable terminal receipt binds inputs and reported observations."""

    schema_version: Literal["lean-verification-record-v1"] = "lean-verification-record-v1"
    request: ArtifactRef
    start: ArtifactRef | None = None
    engine_attempted: bool = False
    outcome: Literal[
        "unsupported",
        "unavailable",
        "deadline",
        "engine_failed",
        "disagreed",
        "verified",
        "cancelled",
        "busy",
    ]
    failure_code: Annotated[str | None, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")] = None
    identity: EngineIdentity | None = None
    raw_output: ArtifactRef | None = None
    observed_nav: Annotated[tuple[NavPoint, ...], Field(max_length=128)] = ()
    cleanup_confirmed: bool | None = None

    @model_validator(mode="after")
    def evidence_coherence(self) -> Self:
        """Agreement needs a complete backend receipt; failure cannot omit its safe code."""
        if self.engine_attempted and self.start is None:
            raise ValueError("Attempted engine work requires a prepared receipt")
        evidence = (
            self.identity is not None,
            self.raw_output is not None,
            bool(self.observed_nav),
            self.cleanup_confirmed is not None,
        )
        if len(set(evidence)) != 1:
            raise ValueError("Engine evidence must be complete or absent")
        if any(evidence) and not self.engine_attempted:
            raise ValueError("Engine evidence requires an attempted operation")
        if self.outcome in {"verified", "disagreed"} and (
            not all(evidence) or self.cleanup_confirmed is not True
        ):
            raise ValueError("Comparison requires complete cleaned engine evidence")
        if (self.outcome == "verified") != (self.failure_code is None):
            raise ValueError("Only verified comparison has no failure code")
        return self


class VerificationStart(Contract):
    """Prepared intent survives a backend crash but does not prove execution began."""

    schema_version: Literal["lean-verification-start-v1"] = "lean-verification-start-v1"
    request: ArtifactRef
    source: ArtifactRef
    reference: ArtifactRef
    identity: EngineIdentity
    prepared_at: UtcText


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys before a source member can silently replace another."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(_: str) -> NoReturn:
    """Nonfinite JSON extensions are outside both source and comparison contracts."""
    raise ValueError("Nonfinite JSON")


def _read(store: ArtifactStore, ref: ArtifactRef) -> bytes:
    """Reread exact actual bytes even when a custom provider claims verified storage."""
    data = store.get(ref)
    if (
        type(data) is not bytes
        or len(data) != ref.size_bytes
        or hashlib.sha256(data).hexdigest() != ref.sha256
    ):
        raise ValueError("Artifact identity mismatch")
    json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
    return data


def _publish(store: ArtifactStore, data: bytes, media_type: str) -> ArtifactRef:
    """Bind the provider's returned reference to the exact bytes actually submitted."""
    ref = ArtifactRef.model_validate(store.put(data, media_type=media_type))
    if (
        ref.size_bytes != len(data)
        or ref.sha256 != hashlib.sha256(data).hexdigest()
        or ref.media_type != media_type
    ):
        raise ValueError("Publication identity mismatch")
    return ref


class LeanVerifier(rpc.LeanVerifierServicer):
    """One cooperative operation per adapter; authenticated hosting is a separate integration.

    An authenticated resolver must construct the Principal from verified transport identity.
    Request ownership is only checked against it, never used to create authority. This class
    opens no listener, adds no capabilities and supplies no default or simulated backend.
    """

    def __init__(
        self,
        store: ArtifactStore,
        *,
        principal_resolver: Callable[[RpcContext], Principal],
        backend: EngineBackend | None = None,
    ) -> None:
        """Bind trusted dependencies and a single local admission slot."""
        self.store = store
        self.principal_resolver = principal_resolver
        self.backend = backend
        self._slot = Lock()
        self._quarantined = False

    def _ready(self) -> EngineIdentity | None:
        """Invalid or unavailable backend identity fails readiness without exposing diagnostics."""
        if self._quarantined:
            return None
        try:
            identity = self.backend.ready() if self.backend is not None else None
            return EngineIdentity.model_validate(identity) if identity is not None else None
        except Exception:
            return None

    def _version(self, request: Message, context: RpcContext) -> None:
        """Both discovery methods require explicit matching wire version before responding."""
        try:
            require_message(request, ("wire_version",))
            if request.wire_version != WIRE_VERSION:
                raise ValueError("Unsupported wire version")
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "LEAN_REQUEST_INVALID")

    def Health(self, request: pb.HealthRequest, context: RpcContext) -> pb.HealthResponse:
        """Handler liveness is separate from current independent-engine readiness."""
        self._version(request, context)
        return pb.HealthResponse(
            wire_version=WIRE_VERSION, alive=True, engine_ready=self._ready() is not None
        )

    def Capabilities(
        self, request: pb.CapabilitiesRequest, context: RpcContext
    ) -> pb.CapabilitiesResponse:
        """Declare the limited prefix and expose whether a real configured backend is ready."""
        self._version(request, context)
        return pb.CapabilitiesResponse(
            wire_version=WIRE_VERSION,
            declared_profiles=[PROFILE],
            ready_profiles=[PROFILE] if self._ready() is not None else [],
            unsupported_features=[
                "shorts",
                "orders",
                "fees",
                "corporate_actions",
                "adjusted_prices",
                "funding_admission",
                "full_factor_verification",
            ],
            max_message_bytes=MAX_MESSAGE_BYTES,
            max_inflight=1,
            max_deadline_seconds=MAX_DEADLINE_SECONDS,
        )

    def _authorize(
        self, message: pb.VerifyStrategyRequest, context: RpcContext
    ) -> VerificationRequest:
        """Reconstruct authority before any store access, readiness check or work allocation."""
        try:
            owner = _principal(self.principal_resolver(context))
            owner.require("execute_lean_verification")
            request = decode_request(message)
            if (request.owner_issuer, request.owner_subject) != (owner.issuer, owner.subject):
                raise ResearchError("FORBIDDEN", "Verification is not permitted.", 403)
            return request
        except ResearchError as error:
            context.abort(
                grpc.StatusCode.PERMISSION_DENIED
                if error.code == "FORBIDDEN"
                else grpc.StatusCode.INVALID_ARGUMENT,
                error.code,
            )
        except Exception:
            context.abort(grpc.StatusCode.PERMISSION_DENIED, "FORBIDDEN")

    def _finish(
        self,
        request: VerificationRequest,
        outcome: str,
        code: str | None,
        context: RpcContext,
        run: EngineRun | None = None,
        *,
        start: ArtifactRef | None = None,
        engine_attempted: bool = False,
    ) -> pb.VerifyStrategyResponse:
        """Publish actual request/raw/terminal bytes before returning their content identities."""
        try:
            request_ref = _publish(self.store, request.canonical_bytes(), "application/json")
            raw_ref = (
                _publish(self.store, run.raw_output, "application/octet-stream")
                if run is not None
                else None
            )
            record = VerificationRecord.model_validate(
                dict(
                    request=request_ref,
                    start=start,
                    engine_attempted=engine_attempted,
                    outcome=outcome,
                    failure_code=code,
                    identity=run.identity if run else None,
                    raw_output=raw_ref,
                    observed_nav=run.points if run else (),
                    cleanup_confirmed=run.cleanup_confirmed if run else None,
                )
            )
            record_ref = _publish(self.store, record.canonical_bytes(), "application/json")
            response = pb.VerifyStrategyResponse(
                outcome=pb.Outcome.Value("OUTCOME_" + outcome.upper()),
                request_sha256=request.sha256,
                record=artifact_to_wire(record_ref),
                observed_nav=[
                    pb.NavPoint(at_utc=point.at, nav_usd=point.nav_usd)
                    for point in record.observed_nav
                ],
            )
            if code is not None:
                response.failure_code = code
            if run is not None:
                response.engine_image_sha256 = run.identity.image_sha256
                response.translator_sha256 = run.identity.translator_sha256
                response.lean_commit = run.identity.lean_commit
            if response.ByteSize() > MAX_MESSAGE_BYTES:
                raise ValueError("Response exceeds bound")
            return response
        except Exception:
            context.abort(grpc.StatusCode.INTERNAL, "LEAN_EVIDENCE_FAILED")

    def _start(
        self, request: VerificationRequest, identity: EngineIdentity, context: RpcContext
    ) -> ArtifactRef:
        """Publish exact prepared lineage before invoking any trusted backend execution."""
        try:
            request_ref = _publish(self.store, request.canonical_bytes(), "application/json")
            receipt = VerificationStart(
                request=request_ref,
                source=request.source,
                reference=request.reference,
                identity=identity,
                prepared_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            return _publish(self.store, receipt.canonical_bytes(), "application/json")
        except Exception:
            context.abort(grpc.StatusCode.INTERNAL, "LEAN_EVIDENCE_FAILED")

    def _stop(self, context: RpcContext, signal: Event, deadline: float) -> str | None:
        """Late completion cannot override a server/client deadline or cancellation signal."""
        remaining = context.time_remaining()
        if (
            time.monotonic() >= deadline
            or remaining is None
            or not math.isfinite(remaining)
            or remaining <= 0
        ):
            signal.set()
            return "deadline"
        if signal.is_set() or not context.is_active():
            signal.set()
            return "cancelled"
        return None

    def VerifyStrategy(
        self, message: pb.VerifyStrategyRequest, context: RpcContext
    ) -> pb.VerifyStrategyResponse:
        """Authorize and compare a backend result without supplying its expected NAV."""
        request = self._authorize(message, context)
        remaining = context.time_remaining()
        if remaining is None or not math.isfinite(remaining) or remaining <= 0:
            return self._finish(request, "deadline", "LEAN_DEADLINE", context)
        deadline = time.monotonic() + min(remaining, MAX_DEADLINE_SECONDS)
        if request.profile != PROFILE:
            return self._finish(request, "unsupported", "LEAN_PROFILE_UNSUPPORTED", context)
        if not self._slot.acquire(blocking=False):
            return self._finish(request, "busy", "LEAN_BUSY", context)
        signal = Event()
        try:
            if not context.add_callback(signal.set):
                signal.set()
            stopped = self._stop(context, signal, deadline)
            if stopped is not None:
                return self._finish(request, stopped, "LEAN_" + stopped.upper(), context)
            identity = self._ready()
            if identity is None or self.backend is None:
                return self._finish(request, "unavailable", "LEAN_UNAVAILABLE", context)
            return self._execute(request, context, signal, deadline, identity)
        finally:
            self._slot.release()

    def _execute(
        self,
        request: VerificationRequest,
        context: RpcContext,
        signal: Event,
        deadline: float,
        identity: EngineIdentity,
    ) -> pb.VerifyStrategyResponse:
        """Keep source loading and engine failures separate from terminal evidence publication."""
        try:
            source = PriceOnlySource.model_validate_json(_read(self.store, request.source))
            reference = NavReference.model_validate_json(_read(self.store, request.reference))
            if reference.source_sha256 != request.source.sha256 or tuple(
                point.at for point in reference.points
            ) != tuple(point.at for point in source.snapshots):
                raise ValueError("Reference source/clock mismatch")
        except ResearchError as error:
            if error.status_code >= 500:
                return self._finish(request, "unavailable", "LEAN_STORAGE_UNAVAILABLE", context)
            return self._finish(request, "unsupported", "LEAN_INPUT_INVALID", context)
        except Exception:
            return self._finish(request, "unsupported", "LEAN_INPUT_INVALID", context)
        stopped = self._stop(context, signal, deadline)
        if stopped is not None:
            return self._finish(request, stopped, "LEAN_" + stopped.upper(), context)
        start = self._start(request, identity, context)
        stopped = self._stop(context, signal, deadline)
        if stopped is not None:
            return self._finish(request, stopped, "LEAN_" + stopped.upper(), context, start=start)
        try:
            assert self.backend is not None
            run = EngineRun.model_validate(
                self.backend.execute(source, cancelled=signal, deadline=deadline)
            )
        except Exception:
            self._quarantined = True
            return self._finish(
                request,
                "engine_failed",
                "LEAN_ENGINE_FAILED",
                context,
                start=start,
                engine_attempted=True,
            )
        if not run.cleanup_confirmed:
            self._quarantined = True
        stopped = self._stop(context, signal, deadline)
        if stopped is not None:
            return self._finish(
                request,
                stopped,
                "LEAN_" + stopped.upper(),
                context,
                run,
                start=start,
                engine_attempted=True,
            )
        if not run.cleanup_confirmed:
            return self._finish(
                request,
                "engine_failed",
                "LEAN_CLEANUP_UNCONFIRMED",
                context,
                run,
                start=start,
                engine_attempted=True,
            )
        if run.identity != identity or self._ready() != identity:
            return self._finish(
                request,
                "engine_failed",
                "LEAN_IDENTITY_CHANGED",
                context,
                run,
                start=start,
                engine_attempted=True,
            )
        if tuple(point.at for point in run.points) != tuple(point.at for point in source.snapshots):
            return self._finish(
                request,
                "engine_failed",
                "LEAN_OBSERVATIONS_INVALID",
                context,
                run,
                start=start,
                engine_attempted=True,
            )
        agrees = all(
            Decimal(actual.nav_usd) == Decimal(expected.nav_usd)
            for actual, expected in zip(run.points, reference.points, strict=True)
        )
        return self._finish(
            request,
            "verified" if agrees else "disagreed",
            None if agrees else "LEAN_NAV_DISAGREED",
            context,
            run,
            start=start,
            engine_attempted=True,
        )
