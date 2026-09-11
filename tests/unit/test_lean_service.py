"""Unit backends exercise RPC lifecycle; none constitutes an actual LEAN verification."""

import hashlib
import json
from collections.abc import Callable
from threading import Event
from typing import NoReturn

import grpc
import pytest
from pydantic import ValidationError
from test_lean_contract import source
from test_lean_wire import request

from factorforge.auth.principal import Principal
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.interop.lean import lean_pb2 as pb
from factorforge.interop.lean.contract import NavPoint, NavReference, PriceOnlySource
from factorforge.interop.lean.service import (
    EngineIdentity,
    EngineRun,
    LeanVerifier,
    VerificationRecord,
)
from factorforge.interop.lean.wire import WIRE_VERSION, encode_request


class MemoryStore:
    """Original test bytes provide observable storage access and immutable identities."""

    def __init__(self) -> None:
        """Start with no objects or access calls."""
        self.objects: dict[str, bytes] = {}
        self.reads = 0
        self.writes = 0

    def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Record exact published bytes without touching the host filesystem."""
        self.writes += 1
        ref = ArtifactRef(
            sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), media_type=media_type
        )
        self.objects[ref.sha256] = data
        return ref

    def get(self, ref: ArtifactRef) -> bytes:
        """Count reads so denied requests cannot silently inspect another owner's inputs."""
        self.reads += 1
        return self.objects[ref.sha256]


class Aborted(Exception):
    """The fake context models gRPC's nonreturning abort without opening a listener."""


class Context:
    """A controllable transport clock and cancellation callback drive deterministic tests."""

    def __init__(self, remaining: float | None = 30.0) -> None:
        """A finite initial deadline models a correctly configured client."""
        self.remaining = remaining
        self.active = True
        self.callback: Callable[[], None] | None = None

    def time_remaining(self) -> float | None:
        """Return the client deadline independently of the server's monotonic clock."""
        return self.remaining

    def is_active(self) -> bool:
        """Expose transport cancellation before or during backend work."""
        return self.active

    def add_callback(self, callback: Callable[[], None]) -> bool:
        """Retain the backend cancellation signal exactly as a gRPC context does."""
        self.callback = callback
        return self.active

    def abort(self, code: grpc.StatusCode, details: str) -> NoReturn:
        """Keep only safe application details in the unit abort result."""
        raise Aborted(code, details)


class Backend:
    """An explicitly fake backend only tests schema and comparison plumbing."""

    def __init__(self) -> None:
        """Use valid test identities and one original observation."""
        self.identity = EngineIdentity(image_sha256="b" * 64, translator_sha256="c" * 64)
        self.calls = 0
        self.hook: Callable[[Event], None] | None = None
        self.nav = "1000"
        self.cleanup = True

    def ready(self) -> EngineIdentity | None:
        """Return a unit identity, never inspect or start a real engine."""
        return self.identity

    def execute(self, value: PriceOnlySource, *, cancelled: Event, deadline: float) -> EngineRun:
        """Accept source alone; the expected reference cannot enter this interface."""
        self.calls += 1
        assert value == source()
        assert deadline > 0
        if self.hook is not None:
            self.hook(cancelled)
        return EngineRun(
            identity=self.identity,
            points=tuple(
                NavPoint(at=row.at, nav_usd=nav)
                for row, nav in zip(value.snapshots, (self.nav, "1020", "1040"), strict=True)
            ),
            raw_output=b"original unit engine output",
            cleanup_confirmed=self.cleanup,
        )


def prepared(
    backend: Backend | None = None,
) -> tuple[LeanVerifier, MemoryStore, pb.VerifyStrategyRequest]:
    """Bind actual source and a separate original reference to one authorized request."""
    store = MemoryStore()
    source_ref = store.put(source().canonical_bytes(), media_type="application/json")
    expected = NavReference(
        schema_version="lean-nav-reference-v1",
        source_sha256=source_ref.sha256,
        points=tuple(
            NavPoint(at=row.at, nav_usd=nav)
            for row, nav in zip(source().snapshots, ("1000", "1020", "1040"), strict=True)
        ),
    )
    reference_ref = store.put(expected.canonical_bytes(), media_type="application/json")
    value = request().model_copy(update={"source": source_ref, "reference": reference_ref})
    principal = Principal("local", "owner", frozenset({"execute_lean_verification"}))
    return (
        LeanVerifier(store, principal_resolver=lambda _: principal, backend=backend),
        store,
        encode_request(value),
    )


def test_default_is_alive_but_unavailable_and_never_executes() -> None:
    """Generated RPC handlers do not masquerade as an installed independent engine."""
    service, store, value = prepared()
    health = service.Health(pb.HealthRequest(wire_version=WIRE_VERSION), Context())
    assert health.alive and not health.engine_ready
    caps = service.Capabilities(pb.CapabilitiesRequest(wire_version=WIRE_VERSION), Context())
    assert not caps.ready_profiles and caps.max_inflight == 1
    result = service.VerifyStrategy(value, Context())
    assert result.outcome == pb.OUTCOME_UNAVAILABLE and result.HasField("record")
    assert store.reads == 0


def test_authority_and_owner_fail_before_any_storage_or_backend() -> None:
    """Existing research rights do not grant the distinct LEAN execution capability."""
    backend = Backend()
    service, store, value = prepared(backend)
    value.owner_subject = "other"
    writes = store.writes
    with pytest.raises(Aborted):
        service.VerifyStrategy(value, Context())
    assert store.reads == 0 and store.writes == writes and backend.calls == 0


@pytest.mark.parametrize(
    "nav,outcome", [("1000.0", pb.OUTCOME_VERIFIED), ("999", pb.OUTCOME_DISAGREED)]
)
def test_exact_comparison_and_raw_evidence(nav: str, outcome: int) -> None:
    """Decimal equality ignores harmless notation while every changed numeric NAV disagrees."""
    backend = Backend()
    backend.nav = nav
    service, store, value = prepared(backend)
    result = service.VerifyStrategy(value, Context())
    assert result.outcome == outcome and backend.calls == 1
    assert result.observed_nav[0].nav_usd == nav
    assert b"original unit engine output" in store.objects.values()


@pytest.mark.parametrize("remaining", [None, float("nan"), float("inf"), -1.0, 0.0])
def test_missing_or_expired_deadline_prevents_engine_work(remaining: float | None) -> None:
    """Unbounded and already expired clients cannot acquire a live engine operation."""
    backend = Backend()
    service, _, value = prepared(backend)
    response = service.VerifyStrategy(value, Context(remaining))
    assert response.outcome == pb.OUTCOME_DEADLINE and backend.calls == 0


def test_transport_cancellation_signals_backend_and_prevents_verified() -> None:
    """Even a numerically matching late result cannot turn cancelled work into verified."""
    backend = Backend()
    context = Context()

    def cancel(signal: Event) -> None:
        """Invoke the registered transport callback while backend work owns the slot."""
        context.active = False
        assert context.callback is not None
        context.callback()
        assert signal.is_set()

    backend.hook = cancel
    service, _, value = prepared(backend)
    assert service.VerifyStrategy(value, context).outcome == pb.OUTCOME_CANCELLED


def test_unconfirmed_cleanup_never_produces_verified() -> None:
    """Observation agreement does not replace a confirmed engine resource teardown."""
    backend = Backend()
    backend.cleanup = False
    service, _, value = prepared(backend)
    result = service.VerifyStrategy(value, Context())
    assert result.outcome == pb.OUTCOME_ENGINE_FAILED
    assert result.failure_code == "LEAN_CLEANUP_UNCONFIRMED"


def test_second_call_is_busy_until_first_backend_returns() -> None:
    """Nested admission demonstrates the nonblocking slot without timing-dependent threads."""
    backend = Backend()
    service, _, value = prepared(backend)

    def nested(_: Event) -> None:
        """Another authorized call cannot multiply the single worker budget."""
        assert service.VerifyStrategy(value, Context()).outcome == pb.OUTCOME_BUSY

    backend.hook = nested
    assert service.VerifyStrategy(value, Context()).outcome == pb.OUTCOME_VERIFIED
    assert backend.calls == 1


def test_unconfirmed_cleanup_quarantines_adapter_before_another_launch() -> None:
    """A released method lock cannot permit accumulation of unconfirmed live engine work."""
    backend = Backend()
    backend.cleanup = False
    service, _, value = prepared(backend)
    assert service.VerifyStrategy(value, Context()).outcome == pb.OUTCOME_ENGINE_FAILED
    assert service.VerifyStrategy(value, Context()).outcome == pb.OUTCOME_UNAVAILABLE
    assert backend.calls == 1
    assert not service.Health(pb.HealthRequest(wire_version=WIRE_VERSION), Context()).engine_ready


def test_forged_publication_identity_cannot_return_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A custom store cannot replace the identity of actual published terminal evidence."""
    service, store, value = prepared(Backend())
    original = store.put

    def forged(data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Simulate a faulty provider returning an unrelated but well-formed content hash."""
        return original(data, media_type=media_type).model_copy(update={"sha256": "f" * 64})

    monkeypatch.setattr(store, "put", forged)
    with pytest.raises(Aborted, match="LEAN_EVIDENCE_FAILED"):
        service.VerifyStrategy(value, Context())


@pytest.mark.parametrize("version", [None, "future-rpc-v9"])
def test_discovery_requires_wire_version(version: str | None) -> None:
    """Readiness cannot be interpreted through an absent or incompatible wire contract."""
    service, _, _ = prepared()
    value = pb.HealthRequest()
    if version is not None:
        value.wire_version = version
    with pytest.raises(Aborted, match="LEAN_REQUEST_INVALID"):
        service.Health(value, Context())


def test_readiness_failure_is_unavailable_without_backend_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An engine inventory fault never becomes a readiness success or public host traceback."""
    backend = Backend()

    def broken() -> EngineIdentity:
        """Simulate an unavailable local runtime with a private diagnostic."""
        raise RuntimeError("private host diagnostic")

    monkeypatch.setattr(backend, "ready", broken)
    service, _, value = prepared(backend)
    result = service.VerifyStrategy(value, Context())
    assert result.outcome == pb.OUTCOME_UNAVAILABLE
    assert "private" not in str(result)


def test_capability_and_resolver_failures_cannot_touch_storage() -> None:
    """A caller's research capability and a failing identity resolver both fail closed."""
    service, store, value = prepared(Backend())
    initial = store.writes
    service.principal_resolver = lambda _: Principal("local", "owner", frozenset({"create_run"}))
    with pytest.raises(Aborted, match="FORBIDDEN"):
        service.VerifyStrategy(value, Context())

    def broken(_: object) -> Principal:
        """Simulate authentication infrastructure failure without revealing its exception."""
        raise RuntimeError("private identity failure")

    service.principal_resolver = broken
    with pytest.raises(Aborted, match="FORBIDDEN"):
        service.VerifyStrategy(value, Context())
    assert store.reads == 0 and store.writes == initial


def test_authorized_malformed_wire_and_unknown_profile_do_not_execute() -> None:
    """Transport errors abort safely; valid unsupported profiles return an explicit outcome."""
    backend = Backend()
    service, store, value = prepared(backend)
    value.ClearField("comparison")
    with pytest.raises(Aborted, match="LEAN_REQUEST_INVALID"):
        service.VerifyStrategy(value, Context())
    value.comparison = pb.COMPARISON_EXACT_NAV
    value.profile = "future-profile"
    assert service.VerifyStrategy(value, Context()).outcome == pb.OUTCOME_UNSUPPORTED
    assert backend.calls == 0 and store.reads == 0


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", b"[" * 1200, b"{}"])
def test_malformed_actual_source_is_archived_failure_without_engine(raw: bytes) -> None:
    """Duplicate/nonfinite/deep/invalid input bytes cannot be coerced into supported source."""
    backend = Backend()
    service, store, value = prepared(backend)
    source_ref = store.put(raw, media_type="application/json")
    value.source.sha256 = source_ref.sha256
    value.source.size_bytes = source_ref.size_bytes
    result = service.VerifyStrategy(value, Context())
    assert result.failure_code == "LEAN_INPUT_INVALID" and backend.calls == 0


def test_artifact_tamper_and_reference_substitution_fail_before_engine() -> None:
    """Reference source identity and actual store bytes are checked separately."""
    backend = Backend()
    service, store, value = prepared(backend)
    original = store.objects[value.source.sha256]
    store.objects[value.source.sha256] = original + b" "
    assert service.VerifyStrategy(value, Context()).failure_code == "LEAN_INPUT_INVALID"
    store.objects[value.source.sha256] = original
    reference = NavReference.model_validate_json(store.objects[value.reference.sha256])
    raw = reference.model_copy(update={"source_sha256": "f" * 64}).canonical_bytes()
    changed = store.put(raw, media_type="application/json")
    value.reference.sha256 = changed.sha256
    value.reference.size_bytes = changed.size_bytes
    assert service.VerifyStrategy(value, Context()).failure_code == "LEAN_INPUT_INVALID"
    assert backend.calls == 0


def test_already_cancelled_context_never_starts_backend() -> None:
    """Failed callback registration is treated as an already terminated transport."""
    backend = Backend()
    service, _, value = prepared(backend)
    context = Context()
    context.active = False
    assert service.VerifyStrategy(value, context).outcome == pb.OUTCOME_CANCELLED
    assert backend.calls == 0


def test_deadline_during_backend_is_signalled_and_cannot_verify() -> None:
    """A late but numerically matching engine result remains deadline failure."""
    backend = Backend()
    context = Context()
    signals: list[Event] = []

    def expire(signal: Event) -> None:
        """Move the client clock past expiry while retaining the backend's cancellation event."""
        context.remaining = 0.0
        signals.append(signal)

    backend.hook = expire
    service, _, value = prepared(backend)
    assert service.VerifyStrategy(value, context).outcome == pb.OUTCOME_DEADLINE
    assert signals[0].is_set()


def test_expiry_during_source_loading_prevents_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Artifact latency consumes the same bounded request deadline as execution."""
    backend = Backend()
    service, store, value = prepared(backend)
    original = store.get
    context = Context()

    def expire(ref: ArtifactRef) -> bytes:
        """Model a store operation which exhausts the remaining client time."""
        context.remaining = 0.0
        return original(ref)

    monkeypatch.setattr(store, "get", expire)
    assert service.VerifyStrategy(value, context).outcome == pb.OUTCOME_DEADLINE
    assert backend.calls == 0


def test_backend_exception_quarantines_and_preserves_safe_failure() -> None:
    """An exceptional return has no cleanup proof and cannot be retried through this adapter."""
    backend = Backend()

    def broken(_: Event) -> None:
        """Simulate failure inside the trusted engine transport."""
        raise RuntimeError("private backend path")

    backend.hook = broken
    service, _, value = prepared(backend)
    result = service.VerifyStrategy(value, Context())
    assert result.failure_code == "LEAN_ENGINE_FAILED" and "private" not in str(result)
    assert service.VerifyStrategy(value, Context()).outcome == pb.OUTCOME_UNAVAILABLE


def test_changed_engine_identity_cannot_verify() -> None:
    """Current identity must match the runtime admitted before source loading."""
    backend = Backend()

    def replace(_: Event) -> None:
        """Change the test engine identity while work is in flight."""
        backend.identity = EngineIdentity(image_sha256="d" * 64, translator_sha256="c" * 64)

    backend.hook = replace
    service, _, value = prepared(backend)
    assert service.VerifyStrategy(value, Context()).failure_code == "LEAN_IDENTITY_CHANGED"


def test_incomplete_engine_observations_cannot_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    """A strict but incomplete row tuple must fail before zip comparison can hide a tail."""
    backend = Backend()
    original = backend.execute

    def incomplete(value: PriceOnlySource, *, cancelled: Event, deadline: float) -> EngineRun:
        """Return one valid observation while omitting two requested clocks."""
        result = original(value, cancelled=cancelled, deadline=deadline)
        return result.model_copy(update={"points": result.points[:1]})

    monkeypatch.setattr(backend, "execute", incomplete)
    service, _, value = prepared(backend)
    assert service.VerifyStrategy(value, Context()).failure_code == "LEAN_OBSERVATIONS_INVALID"


@pytest.mark.parametrize(
    "changes",
    [
        {"identity": Backend().identity},
        {"outcome": "verified", "failure_code": None},
        {"failure_code": None},
    ],
)
def test_saved_terminal_receipts_reject_incoherent_evidence(changes: dict[str, object]) -> None:
    """A loaded receipt cannot make unsupported success claims from incomplete engine fields."""
    value = dict(request=request().source, outcome="unavailable", failure_code="LEAN_UNAVAILABLE")
    with pytest.raises(ValidationError):
        VerificationRecord.model_validate(value | changes)


def test_forged_nested_backend_return_is_revalidated_and_quarantined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Copied malformed output cannot bypass numeric validation or promise known cleanup."""
    backend = Backend()
    original = backend.execute

    def forged(value: PriceOnlySource, *, cancelled: Event, deadline: float) -> EngineRun:
        """Return a copied NaN point that Pydantic model_copy intentionally did not validate."""
        result = original(value, cancelled=cancelled, deadline=deadline)
        point = result.points[0].model_copy(update={"nav_usd": "NaN"})
        return result.model_copy(update={"points": (point, *result.points[1:])})

    monkeypatch.setattr(backend, "execute", forged)
    service, _, value = prepared(backend)
    assert service.VerifyStrategy(value, Context()).failure_code == "LEAN_ENGINE_FAILED"
    assert service.VerifyStrategy(value, Context()).outcome == pb.OUTCOME_UNAVAILABLE


def test_start_receipt_exists_before_backend_and_survives_exception() -> None:
    """A failing engine call still has a pre-call binding of source, reference and identity."""
    backend = Backend()
    service, store, value = prepared(backend)
    starts: list[str] = []

    def fail_after_inspection(_: Event) -> None:
        """Check persisted intent before simulating an exceptional engine transport return."""
        for digest, raw in store.objects.items():
            if b'"schema_version":"lean-verification-start-v1"' in raw:
                record = json.loads(raw)
                assert record["source"]["sha256"] == value.source.sha256
                assert record["reference"]["sha256"] == value.reference.sha256
                assert record["identity"]["image_sha256"] == backend.identity.image_sha256
                starts.append(digest)
        assert len(starts) == 1
        raise RuntimeError("unit transport failure")

    backend.hook = fail_after_inspection
    result = service.VerifyStrategy(value, Context())
    assert len(starts) == 1
    terminal = json.loads(store.objects[result.record.sha256])
    assert terminal["start"]["sha256"] == starts[0]
    assert terminal["engine_attempted"] is True
    assert result.failure_code == "LEAN_ENGINE_FAILED"


def test_start_publication_failure_prevents_backend_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """No code can execute if publishing its pre-call lineage receipt fails."""
    backend = Backend()
    service, store, value = prepared(backend)
    original = store.put

    def fail_start(data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Reject exactly the prepared receipt after canonical request publication."""
        if b'"schema_version":"lean-verification-start-v1"' in data:
            raise RuntimeError("unit store failure")
        return original(data, media_type=media_type)

    monkeypatch.setattr(store, "put", fail_start)
    with pytest.raises(Aborted, match="LEAN_EVIDENCE_FAILED"):
        service.VerifyStrategy(value, Context())
    assert backend.calls == 0


@pytest.mark.parametrize(
    "status,outcome", [(503, pb.OUTCOME_UNAVAILABLE), (404, pb.OUTCOME_UNSUPPORTED)]
)
def test_storage_availability_is_distinct_from_bad_input(
    status: int, outcome: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typed transient provider failure does not claim the immutable source schema is invalid."""
    backend = Backend()
    service, store, value = prepared(backend)

    def unavailable(_: ArtifactRef) -> bytes:
        """Raise the existing artifact provider's safe typed failure boundary."""
        raise ResearchError("ARTIFACT_UNAVAILABLE", "Safe provider failure", status)

    monkeypatch.setattr(store, "get", unavailable)
    assert service.VerifyStrategy(value, Context()).outcome == outcome
    assert backend.calls == 0


def test_expired_start_receipt_is_preserved_without_claiming_engine_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publishing prepared intent can consume the deadline before execution actually begins."""
    backend = Backend()
    service, store, value = prepared(backend)
    original = store.put
    context = Context()

    def expire(data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Expire after the start object is durably accepted by the test store."""
        ref = original(data, media_type=media_type)
        if b'"schema_version":"lean-verification-start-v1"' in data:
            context.remaining = 0.0
        return ref

    monkeypatch.setattr(store, "put", expire)
    result = service.VerifyStrategy(value, context)
    terminal = VerificationRecord.model_validate_json(store.objects[result.record.sha256])
    assert terminal.start is not None and not terminal.engine_attempted
    assert result.outcome == pb.OUTCOME_DEADLINE and backend.calls == 0


def test_saved_attempt_or_backend_evidence_requires_start_lineage() -> None:
    """Reloaded receipts cannot omit the prior intent or claim output from unattempted work."""
    with pytest.raises(ValidationError):
        VerificationRecord(
            request=request().source,
            outcome="engine_failed",
            failure_code="LEAN_ENGINE_FAILED",
            engine_attempted=True,
        )
    backend = Backend()
    run = backend.execute(source(), cancelled=Event(), deadline=1.0)
    with pytest.raises(ValidationError):
        VerificationRecord(
            request=request().source,
            start=request().reference,
            outcome="engine_failed",
            failure_code="LEAN_ENGINE_FAILED",
            identity=run.identity,
            raw_output=request().source,
            observed_nav=run.points,
            cleanup_confirmed=True,
        )


def test_terminal_publication_failure_retains_prepared_and_raw_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No verified response escapes when final publication fails after actual backend return."""
    backend = Backend()
    service, store, value = prepared(backend)
    original = store.put

    def fail_terminal(data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Fail only the terminal object, after prepared and raw-output objects were published."""
        if b'"schema_version":"lean-verification-record-v1"' in data:
            raise RuntimeError("unit terminal failure")
        return original(data, media_type=media_type)

    monkeypatch.setattr(store, "put", fail_terminal)
    with pytest.raises(Aborted, match="LEAN_EVIDENCE_FAILED"):
        service.VerifyStrategy(value, Context())
    assert backend.calls == 1
    assert b"original unit engine output" in store.objects.values()
    assert any(
        b'"schema_version":"lean-verification-start-v1"' in raw for raw in store.objects.values()
    )
