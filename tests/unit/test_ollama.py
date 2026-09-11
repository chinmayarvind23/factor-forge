"""Local model delivery preserves failures without claiming extraction correctness."""

import json
import time
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import cast

import httpx
import pytest

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.providers.ollama import (
    MAX_RESPONSE_BYTES,
    GenerationProfile,
    GenerationRequest,
    GenerationResult,
    OllamaProvider,
)


@pytest.mark.parametrize("model", ["llama3.1:8b", "qwen3:8b"])
def test_model_comparison_preserves_limits_and_explicit_thinking(model: str) -> None:
    """The candidate changes model identity and disables thinking without changing budgets."""
    transport = FixtureTransport(
        response({**valid_reply(), "model": model}),
        inventory={"models": [{"name": model, "digest": "b" * 64}]},
    )
    request = generation_request().model_copy(update={"model": model})
    with TemporaryDirectory() as directory:
        store = LocalArtifactStore(Path(directory))
        result = OllamaProvider(transport=transport).generate(request, store)
        assert result.status == "success"
        record = json.loads(store.get(result.record))
        payload = json.loads(store.get(ArtifactRef.model_validate(record["request"])))
        assert record["model"] == payload["model"] == model
        assert record["model_digest"] == "b" * 64
        assert payload["options"] == {
            "temperature": 0,
            "seed": 0,
            "num_ctx": 32768,
            "num_predict": 2048,
        }
        if model == "qwen3:8b":
            assert payload["think"] is False
        else:
            assert "think" not in payload


def test_worker_deadline_prevents_expired_provider_io() -> None:
    """An already exhausted research allowance still retains a typed delivery record."""
    transport = FixtureTransport(response(valid_reply()))
    with TemporaryDirectory() as directory:
        store = LocalArtifactStore(Path(directory))
        result = OllamaProvider(transport=transport, deadline=0.0).generate(
            generation_request(), store
        )
        assert result.status == "unavailable" and transport.calls == []
        assert store.get(result.record)


def test_worker_deadline_caps_each_http_read() -> None:
    """Every metadata and generation request shares the remaining worker allowance."""
    transport = FixtureTransport(response(valid_reply()))
    with TemporaryDirectory() as directory:
        result = OllamaProvider(transport=transport, deadline=time.monotonic() + 2).generate(
            generation_request(), LocalArtifactStore(Path(directory))
        )
        assert result.status == "success"
        assert all(0 < call.extensions["timeout"]["read"] <= 2 for call in transport.calls)


@pytest.mark.parametrize(
    "profile,context,output,read_cap",
    [
        (GenerationProfile.EXTRACTION_32K_V1, 32768, 2048, 120),
        (GenerationProfile.LOCAL_PROTOCOL_4K_V1, 4096, 128, 180),
    ],
)
def test_fixed_profiles_preserve_wire_options_and_record_identity(
    profile: GenerationProfile,
    context: int,
    output: int,
    read_cap: int,
) -> None:
    """A separate smoke configuration cannot silently weaken the original extraction baseline."""
    transport = FixtureTransport(response(valid_reply()))
    request = generation_request().model_copy(update={"profile": profile})
    with TemporaryDirectory(prefix="factorforge-profile-") as directory:
        store = LocalArtifactStore(Path(directory))
        result = OllamaProvider(transport=transport).generate(request, store)
        record = json.loads(store.get(result.record))
        sent = next(call for call in transport.calls if call.url.path == "/api/chat")
        assert result.status == "success"
        assert json.loads(sent.content)["options"] == {
            "temperature": 0,
            "seed": 0,
            "num_ctx": context,
            "num_predict": output,
        }
        assert sent.content == store.get(ArtifactRef.model_validate(record["request"]))
        assert record["schema_version"] == "local-generation-v2"
        assert record["profile"] == profile.value
        assert read_cap - 5 < transport.calls[0].extensions["timeout"]["read"] <= read_cap
    assert generation_request().profile is GenerationProfile.EXTRACTION_32K_V1


@pytest.mark.parametrize(
    "profile,limit",
    [
        (GenerationProfile.EXTRACTION_32K_V1, 24 * 1024),
        (GenerationProfile.LOCAL_PROTOCOL_4K_V1, 2 * 1024),
    ],
)
def test_profile_exact_request_boundary_precedes_io(
    profile: GenerationProfile,
    limit: int,
) -> None:
    """The complete canonical request, including schema and options, consumes the byte budget."""
    transport = FixtureTransport(response(valid_reply()))
    request = generation_request().model_copy(update={"profile": profile, "user": "x"})
    with TemporaryDirectory(prefix="factorforge-profile-limit-") as directory:
        store = LocalArtifactStore(Path(directory))
        OllamaProvider(transport=transport).generate(request, store)
        overhead = (
            len(next(call.content for call in transport.calls if call.url.path == "/api/chat")) - 1
        )
    for extra in (0, 1):
        transport = FixtureTransport(response(valid_reply()))
        request = request.model_copy(update={"user": "x" * (limit - overhead + extra)})
        with TemporaryDirectory(prefix="factorforge-profile-limit-") as directory:
            store = LocalArtifactStore(Path(directory))
            if extra:
                with pytest.raises(ResearchError) as failure:
                    OllamaProvider(transport=transport).generate(request, store)
                assert failure.value.code == "MODEL_INPUT_INVALID"
                assert not transport.calls and not list(Path(directory).iterdir())
            else:
                result = OllamaProvider(transport=transport).generate(request, store)
                assert result.status == "success"
                assert (
                    len(
                        next(
                            call.content for call in transport.calls if call.url.path == "/api/chat"
                        )
                    )
                    == limit
                )


def test_smoke_profile_rejects_provider_output_above_its_budget() -> None:
    """The smoke call rejects counters above its separately frozen output limit."""
    transport = FixtureTransport(response({**valid_reply(), "eval_count": 129}))
    request = generation_request().model_copy(
        update={"profile": GenerationProfile.LOCAL_PROTOCOL_4K_V1}
    )
    with TemporaryDirectory(prefix="factorforge-profile-output-") as directory:
        store = LocalArtifactStore(Path(directory))
        result = OllamaProvider(transport=transport).generate(request, store)
        assert result.status == "malformed" and result.content is None
        record = json.loads(store.get(result.record))
        assert record["profile"] == "local_protocol_4k_v1"
        assert record["output_tokens"] == 129


def test_forged_profile_cannot_override_limits_or_admit_io() -> None:
    """Only the enum's declared profiles may reach artifact or network admission."""
    transport = FixtureTransport(response(valid_reply()))
    request = generation_request().model_copy(update={"profile": "unbounded"})
    with TemporaryDirectory(prefix="factorforge-profile-invalid-") as directory:
        store = LocalArtifactStore(Path(directory))
        with pytest.raises(ResearchError) as failure:
            OllamaProvider(transport=transport).generate(request, store)
        assert failure.value.code == "MODEL_INPUT_INVALID" and not transport.calls
        assert not list(Path(directory).iterdir())


class ProbeStream(httpx.SyncByteStream):
    """A real streaming interface exposes partial-read failures and verifies connection cleanup."""

    def __init__(self, chunks: list[bytes | Exception]) -> None:
        """Retain controlled frames without starting any network operation."""
        self.chunks = chunks
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        """Emit known prefixes before an injected disconnect or oversized frame."""
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self) -> None:
        """Record stream release on every terminal path."""
        self.closed = True


class FixtureTransport(httpx.BaseTransport):
    """Serve only the fixed local inventory/version/chat routes and record complete closure."""

    def __init__(
        self,
        chat: httpx.Response | Exception,
        *,
        inventory: object = None,
        after: object = None,
        version: object = "fixture",
    ) -> None:
        """Configure identity metadata independently from the generated response."""
        self.chat = chat
        self.inventory = (
            inventory
            if inventory is not None
            else {"models": [{"name": "llama3.1:8b", "digest": "a" * 64}]}
        )
        self.after = self.inventory if after is None else after
        self.version = version
        self.calls: list[httpx.Request] = []
        self.closed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """A redirect cannot escape to another host or introduce a retry through this transport."""
        self.calls.append(request)
        assert str(request.url).startswith("http://127.0.0.1:11434/api/")
        assert request.headers["accept-encoding"] == "identity"
        if request.url.path == "/api/tags":
            return response(self.inventory if len(self.calls) == 1 else self.after)
        if request.url.path == "/api/version":
            return response({"version": self.version})
        if isinstance(self.chat, Exception):
            raise self.chat
        return self.chat

    def close(self) -> None:
        """Record client/transport cleanup even when parsing or artifact persistence fails."""
        self.closed = True


def exercise(
    transport: FixtureTransport,
    profile: GenerationProfile = GenerationProfile.EXTRACTION_32K_V1,
) -> tuple[GenerationResult, dict[str, object], bytes | None]:
    """Load saved evidence through the verifying store before releasing its workspace."""
    with TemporaryDirectory(prefix="factorforge-provider-probe-") as directory:
        store = LocalArtifactStore(Path(directory))
        request = generation_request().model_copy(update={"profile": profile})
        result = OllamaProvider(transport=transport).generate(request, store)
        record = cast(dict[str, object], json.loads(store.get(result.record)))
        raw = (
            store.get(ArtifactRef.model_validate(record["response"]))
            if record["response"] is not None
            else None
        )
        return result, record, raw


@pytest.mark.parametrize(
    "case",
    [
        "oversize",
        "partial_timeout",
        "invalid_utf8",
        "deep",
        "compressed",
        "redirect",
        "empty",
        "array",
        "bad_syntax",
    ],
)
def test_stream_failures_preserve_bounded_evidence_and_close(case: str) -> None:
    """Retain bounded bytes on malformed, oversized and incomplete responses."""
    data = json.dumps(valid_reply()).encode()
    chunks: list[bytes | Exception] = [data]
    status = "malformed"
    headers: dict[str, str] = {}
    http_status = 200
    complete = True
    if case == "oversize":
        chunks = [b"x" * (MAX_RESPONSE_BYTES * 3)]
        complete = False
    elif case == "partial_timeout":
        chunks = [b'{"partial":', httpx.ReadTimeout("sensitive transport details")]
        status, complete = "unavailable", False
    elif case == "invalid_utf8":
        chunks = [b"\xff"]
    elif case == "deep":
        chunks = [b'{"nested":' + b"[" * 33 + b"0" + b"]" * 33 + b"}"]
    elif case == "compressed":
        headers = {"content-encoding": "gzip"}
    elif case == "redirect":
        headers, http_status, status = {"location": "https://untrusted.example"}, 307, "unavailable"
    elif case == "empty":
        chunks = []
    elif case == "array":
        chunks = [b"[]"]
    elif case == "bad_syntax":
        chunks = [b'{"partial":']
    stream = ProbeStream(chunks)
    transport = FixtureTransport(httpx.Response(http_status, headers=headers, stream=stream))
    result, record, raw = exercise(transport)
    assert result.status == status and result.content is None
    assert cast(dict[str, bool], record["capture_complete"])["response"] is complete
    assert cast(dict[str, int], record["http_statuses"])["response"] == http_status
    assert raw is not None and len(raw) <= MAX_RESPONSE_BYTES
    if case == "oversize":
        assert raw == b"x" * MAX_RESPONSE_BYTES
    if case == "partial_timeout":
        assert raw == b'{"partial":'
    assert stream.closed and transport.closed
    assert sum(request.url.path == "/api/chat" for request in transport.calls) == 1


@pytest.mark.parametrize(
    "case,status",
    [
        ("missing", "unavailable"),
        ("duplicate", "unavailable"),
        ("invalid_digest", "malformed"),
        ("wrong_shape", "malformed"),
        ("changed", "malformed"),
        ("version", "malformed"),
    ],
)
def test_inventory_identity_failures_never_produce_success(case: str, status: str) -> None:
    """Missing or changed models cannot become silent downloads or ambiguous lineage."""
    inventory: object = None
    after: object = None
    version: object = "fixture"
    if case == "missing":
        inventory = {"models": []}
    elif case == "duplicate":
        inventory = {"models": [{"name": "llama3.1:8b", "digest": "a" * 64}] * 2}
    elif case == "invalid_digest":
        inventory = {"models": [{"name": "llama3.1:8b", "digest": "not a hash"}]}
    elif case == "wrong_shape":
        inventory = {"models": "not a list"}
    elif case == "changed":
        after = {"models": [{"name": "llama3.1:8b", "digest": "b" * 64}]}
    elif case == "version":
        version = " "
    transport = FixtureTransport(
        response(valid_reply()), inventory=inventory, after=after, version=version
    )
    result, _, _ = exercise(transport)
    assert result.status == status and result.content is None and transport.closed
    assert sum(request.url.path == "/api/chat" for request in transport.calls) == (
        case == "changed"
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"done": False},
        {"done": "true"},
        {"model": "other"},
        {"eval_count": True},
        {"eval_count": 2049},
        {"total_duration": -1},
        {"message": {"role": "assistant", "content": "text", "tool_calls": [{"name": "run"}]}},
    ],
)
def test_invalid_delivery_metadata_is_rejected(updates: dict[str, object]) -> None:
    """Only completed text delivery with valid counters and the requested model is accepted."""
    transport = FixtureTransport(response({**valid_reply(), **updates}))
    result, _, raw = exercise(transport)
    assert result.status == "malformed" and raw is not None and transport.closed


@pytest.mark.parametrize("case", ["oversize", "nan_schema", "forged", "deep_schema"])
def test_request_rejection_precedes_artifact_and_network_io(case: str) -> None:
    """Oversized or forged input is rejected before an attempt, without leaking prompt content."""
    request = generation_request()
    if case == "oversize":
        request = request.model_copy(update={"user": "x" * 30000})
    elif case == "nan_schema":
        request.response_schema["unexpected"] = float("nan")
    elif case == "forged":
        request = GenerationRequest.model_construct(
            model="untrusted", system="x", user="x", response_schema={}
        )
    elif case == "deep_schema":
        nested: dict[str, object] = {}
        for _ in range(40):
            nested = {"properties": nested}
        request = request.model_copy(update={"response_schema": nested})
    transport = FixtureTransport(response(valid_reply()))
    with TemporaryDirectory(prefix="factorforge-provider-input-") as directory:
        root = Path(directory)
        store = LocalArtifactStore(root)
        with pytest.raises(ResearchError) as failure:
            OllamaProvider(transport=transport).generate(request, store)
        assert failure.value.code == "MODEL_INPUT_INVALID"
        assert not list(root.iterdir()) and not transport.calls


@pytest.mark.parametrize("expire_at", ["admission", "chunk", "eof"])
@pytest.mark.parametrize("profile", list(GenerationProfile))
def test_elapsed_deadline_blocks_admission_and_late_eof(
    expire_at: str,
    profile: GenerationProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An expired budget blocks HTTP admission and cannot be revived by a late complete body."""
    clock = SimpleNamespace(value=0.0)

    def now() -> float:
        """Only the provider's clock changes; HTTPX and pytest retain their real clocks."""
        value = float(clock.value)
        if expire_at == "admission":
            clock.value = 181.0
        return value

    class LateStream(ProbeStream):
        """The final network frame can finish after the elapsed budget has expired."""

        def __iter__(self) -> Iterator[bytes]:
            """Advance time at EOF after one complete JSON object was delivered."""
            if expire_at == "chunk":
                clock.value = 181.0
            yield json.dumps(valid_reply()).encode()
            clock.value = 181.0

    stream = LateStream([])
    transport = FixtureTransport(httpx.Response(200, stream=stream))
    monkeypatch.setattr("factorforge.providers.ollama.time", SimpleNamespace(monotonic=now))
    result, record, _ = exercise(transport, profile)
    assert result.status == "unavailable" and result.content is None
    assert transport.closed
    if expire_at != "admission":
        assert stream.closed
        assert cast(dict[str, bool], record["capture_complete"])["response"] is (expire_at == "eof")
    else:
        assert not transport.calls
        assert cast(dict[str, bool], record["capture_complete"])["inventory"] is False


@pytest.mark.parametrize(
    "profile,read_cap",
    [
        (GenerationProfile.EXTRACTION_32K_V1, 120),
        (GenerationProfile.LOCAL_PROTOCOL_4K_V1, 180),
    ],
)
def test_remaining_deadline_reduces_later_http_timeouts(
    monkeypatch: pytest.MonkeyPatch,
    profile: GenerationProfile,
    read_cap: int,
) -> None:
    """Each subsequent call receives the remaining elapsed budget rather than a fresh timeout."""
    clock = SimpleNamespace(value=0.0)

    class SlowInventory(FixtureTransport):
        """Consume time during the first inventory read without a real wait."""

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            """Later requests must observe the time already spent checking the model inventory."""
            reply = super().handle_request(request)
            clock.value = 100.0
            return reply

    monkeypatch.setattr(
        "factorforge.providers.ollama.time", SimpleNamespace(monotonic=lambda: clock.value)
    )
    transport = SlowInventory(response(valid_reply()))
    result, _, _ = exercise(transport, profile)
    assert result.status == "success"
    assert transport.calls[0].extensions["timeout"]["read"] == read_cap
    assert transport.calls[1].extensions["timeout"]["read"] == 80


def test_wire_request_equals_archive_despite_nested_caller_mutation() -> None:
    """Mutating the caller's nested schema after admission cannot change the archived wire bytes."""
    request = generation_request()
    request.response_schema["properties"] = {"status": {"type": "string"}}

    class MutatingStore(LocalArtifactStore):
        """Change the caller object only after the provider has snapshotted its request."""

        def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
            """Artifact persistence is an I/O boundary where caller-owned data could change."""
            properties = cast(dict[str, object], request.response_schema["properties"])
            cast(dict[str, object], properties["status"])["type"] = "array"
            return super().put(data, media_type=media_type)

    transport = FixtureTransport(response(valid_reply()))
    with TemporaryDirectory(prefix="factorforge-provider-snapshot-") as directory:
        store = MutatingStore(Path(directory))
        result = OllamaProvider(transport=transport).generate(request, store)
        record = json.loads(store.get(result.record))
        archived = store.get(ArtifactRef.model_validate(record["request"]))
        sent = next(call.content for call in transport.calls if call.url.path == "/api/chat")
        assert sent == archived
        assert json.loads(sent)["format"]["properties"]["status"]["type"] == "string"


@pytest.mark.parametrize("fail_at", [1, 4, 6])
def test_evidence_storage_failure_never_returns_success(fail_at: int) -> None:
    """Missing request, response or call-record evidence prevents success."""

    class FailingStore(LocalArtifactStore):
        """Inject disk failure at a specific lineage boundary using the real store otherwise."""

        calls = 0

        def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
            """Fail the selected evidence write instead of inventing a stored reference."""
            self.calls += 1
            if self.calls == fail_at:
                raise ResearchError("ARTIFACT_IO", "Artifact storage failed.", 503)
            return super().put(data, media_type=media_type)

    stream = ProbeStream([json.dumps(valid_reply()).encode()])
    transport = FixtureTransport(httpx.Response(200, stream=stream))
    with TemporaryDirectory(prefix="factorforge-provider-evidence-") as directory:
        with pytest.raises(ResearchError) as failure:
            OllamaProvider(transport=transport).generate(
                generation_request(), FailingStore(Path(directory))
            )
        assert failure.value.code == "ARTIFACT_IO"
    if fail_at == 1:
        assert not transport.calls
    else:
        assert stream.closed and transport.closed


def test_escaped_brackets_and_finite_extra_numbers_are_not_misparsed() -> None:
    """Depth checking treats bracket characters inside escaped JSON strings as ordinary content."""
    content = '"quoted" \\ ' + "[" * 100
    value = {**valid_reply(), "message": {"role": "assistant", "content": content}, "extra": 1.5}
    result, _, _ = exercise(FixtureTransport(response(value)))
    assert result.status == "success" and result.content == content


def generation_request() -> GenerationRequest:
    """Protocol tests contain no factor facts, retrieval labels or evaluated extraction prompts."""
    return GenerationRequest(
        model="llama3.1:8b",
        system="Return JSON only.",
        user="Status probe.",
        response_schema={"type": "object"},
    )


def valid_reply() -> dict[str, object]:
    """Provider delivery fields are separate from semantic validation of the returned content."""
    return {
        "model": "llama3.1:8b",
        "done": True,
        "done_reason": "stop",
        "message": {"role": "assistant", "content": '{"status":"ok"}'},
        "prompt_eval_count": 12,
        "eval_count": 6,
        "total_duration": 1000000,
    }


@pytest.mark.parametrize("variant", ["integer_done", "duplicate", "nonfinite", "overflow_float"])
def test_ambiguous_provider_json_is_never_success(variant: str) -> None:
    """Reject duplicate fields and nonstandard numbers before parser normalization."""
    value = valid_reply()
    if variant == "integer_done":
        value["done"] = 1
    raw = json.dumps(value).encode()
    if variant == "duplicate":
        raw = raw[:-1] + b',"done":false,"done":true}'
    if variant == "nonfinite":
        raw = raw[:-1] + b',"ignored":NaN}'
    if variant == "overflow_float":
        raw = raw[:-1] + b',"ignored":1e999}'

    def transport(request: httpx.Request) -> httpx.Response:
        """Only the chat response varies; all inventory metadata remains a controlled constant."""
        if request.url.path == "/api/tags":
            return response({"models": [{"name": "llama3.1:8b", "digest": "a" * 64}]})
        if request.url.path == "/api/version":
            return response({"version": "fixture"})
        return httpx.Response(200, stream=httpx.ByteStream(raw))

    with TemporaryDirectory(prefix="factorforge-model-json-") as directory:
        store = LocalArtifactStore(Path(directory))
        result = OllamaProvider(transport=httpx.MockTransport(transport)).generate(
            generation_request(), store
        )
        assert result.status == "malformed"
        record = json.loads(store.get(result.record))
        assert record["capture_complete"]["response"] is True
        assert record["response"] is not None


def response(value: object) -> httpx.Response:
    """An actual unread byte stream exercises raw response bounds rather than preloaded content."""
    return httpx.Response(200, stream=httpx.ByteStream(json.dumps(value).encode()))


@pytest.mark.parametrize("outcome", ["success", "truncated", "malformed", "unavailable"])
def test_model_outcomes_preserve_actual_request_and_response(outcome: str) -> None:
    """A real HTTPX transport boundary exercises finite requests without model evaluation."""
    calls: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        """Supply protocol responses and inspect endpoint and generation constraints."""
        calls.append(request.url.path)
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/api/tags":
            return response({"models": [{"name": "llama3.1:8b", "digest": "a" * 64}]})
        if request.url.path == "/api/version":
            return response({"version": "fixture-service"})
        body = json.loads(request.content)
        assert body["stream"] is False
        assert body["options"]["num_predict"] == 2048
        assert "tools" not in body
        if outcome == "unavailable":
            raise httpx.ReadTimeout("sensitive diagnostic")
        if outcome == "malformed":
            return response({"message": {"content": "sensitive malformed"}})
        return response(
            {
                "model": "llama3.1:8b",
                "done": True,
                "done_reason": "length" if outcome == "truncated" else "stop",
                "message": {"role": "assistant", "content": '{"status":"ok"}'},
                "prompt_eval_count": 12,
                "eval_count": 6,
                "total_duration": 1000000,
            },
        )

    with TemporaryDirectory(prefix="factorforge-model-") as directory:
        store = LocalArtifactStore(Path(directory))
        provider = OllamaProvider(transport=httpx.MockTransport(transport))
        result = provider.generate(
            GenerationRequest(
                model="llama3.1:8b",
                system="Return only the requested JSON.",
                user="A protocol smoke test.",
                response_schema={
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                    "additionalProperties": False,
                },
            ),
            store,
        )
        assert result.status == outcome
        record = json.loads(store.get(result.record))
        assert record["billing"] == "local_unmeasured"
        assert record["model_digest"] == "a" * 64
        assert record["request"]["sha256"]
        assert (
            record["response"] is not None
            if outcome != "unavailable"
            else record["response"] is None
        )
        assert (
            result.content == '{"status":"ok"}' if outcome == "success" else result.content is None
        )
        assert calls.count("/api/chat") == 1
