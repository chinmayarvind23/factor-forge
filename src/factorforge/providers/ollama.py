"""One bounded local generation attempt with archived evidence and no inferred dollar cost."""

import json
import math
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Literal, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError

MAX_RESPONSE_BYTES = 512 * 1024
MAX_REQUEST_BYTES = 24 * 1024
MAX_JSON_DEPTH = 32
type Outcome = Literal["success", "truncated", "malformed", "unavailable"]


@dataclass(frozen=True, slots=True)
class _ProfileLimits:
    """Frozen admission and output limits prevent caller-supplied tuning of a named baseline."""

    context: int
    output: int
    request_bytes: int
    read_seconds: int


class GenerationProfile(StrEnum):
    """Protocol delivery probes have an explicit identity separate from extraction experiments."""

    EXTRACTION_32K_V1 = "extraction_32k_v1"
    LOCAL_PROTOCOL_4K_V1 = "local_protocol_4k_v1"

    @property
    def limits(self) -> _ProfileLimits:
        """The smoke probe reserves 1,920 tokens beyond admitted bytes and maximum output."""
        if self is GenerationProfile.LOCAL_PROTOCOL_4K_V1:
            return _ProfileLimits(4096, 128, 2048, 180)
        return _ProfileLimits(32768, 2048, MAX_REQUEST_BYTES, 120)


class GenerationRequest(BaseModel):
    """Trusted prompts and a schema are revalidated and snapshotted before any admitted call."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )
    model: Literal["llama3.1:8b", "qwen3:8b"]
    profile: GenerationProfile = GenerationProfile.EXTRACTION_32K_V1
    system: str = Field(min_length=1, max_length=16000)
    user: str = Field(min_length=1, max_length=32000)
    response_schema: dict[str, JsonValue]


class GenerationResult(BaseModel):
    """Success means provider delivery; a separate extraction layer must validate semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    status: Outcome
    record: ArtifactRef
    content: str | None


class _Message(BaseModel):
    """A tool call is not accepted as a text response from this tool-free provider profile."""

    model_config = ConfigDict(extra="ignore", strict=True)
    role: Literal["assistant"]
    content: str = Field(max_length=65536)
    tool_calls: list[JsonValue] = Field(default_factory=list, max_length=0)


class _Response(BaseModel):
    """A strict boolean and integer counters reject truthy values and nonfinite measurements."""

    model_config = ConfigDict(extra="ignore", strict=True)
    model: str = Field(min_length=1, max_length=128)
    done: bool
    done_reason: Literal["stop", "length"]
    message: _Message
    prompt_eval_count: Annotated[int, Field(ge=0, le=1000000)]
    eval_count: Annotated[int, Field(ge=0, le=2048)]
    total_duration: Annotated[int, Field(ge=0, le=2**63 - 1)]


class _CallRecord(BaseModel):
    """Every admitted attempt retains prompt, raw captures and an explicit measurement scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["local-generation-v2"] = "local-generation-v2"
    provider: Literal["ollama-loopback"] = "ollama-loopback"
    profile: GenerationProfile
    status: Outcome
    model: str
    model_digest: str | None
    server_version: str | None
    request: ArtifactRef
    response: ArtifactRef | None
    captures: dict[str, ArtifactRef]
    capture_complete: dict[str, bool]
    http_statuses: dict[str, int]
    wall_ms: int
    prompt_tokens: int | None
    output_tokens: int | None
    provider_duration_ns: int | None
    billing: Literal["local_unmeasured"] = "local_unmeasured"


@dataclass
class _Captures:
    """One attempt owns its evidence inventory, including failed prefixes and HTTP statuses."""

    artifacts: dict[str, ArtifactRef] = field(default_factory=dict)
    complete: dict[str, bool] = field(default_factory=dict)
    statuses: dict[str, int] = field(default_factory=dict)


def _json_bytes(value: object) -> bytes:
    """Canonical JSON exposes prompt/options changes through the exact request artifact hash."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _check_depth(data: bytes) -> None:
    """Bound container depth before parsing; ignore escaped string content."""
    depth = 0
    quoted = False
    escaped = False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("Provider JSON exceeds its depth limit")
        elif byte in (93, 125):
            depth -= 1


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    """Reject duplicate keys at every JSON-object level before they overwrite earlier values."""
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Provider JSON contains duplicate keys")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    """Reject exponent overflow as well as named NaN/Infinity tokens, even in ignored fields."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Provider JSON contains a nonfinite number")
    return number


def _response_object(data: bytes) -> dict[str, JsonValue]:
    """UTF-8 JSON must be one bounded object with unambiguous keys and finite numbers."""
    _check_depth(data)
    value = json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_float=_finite_float,
        parse_constant=_finite_float,
    )
    if not isinstance(value, dict):
        raise ValueError("Provider response must be an object")
    return cast(dict[str, JsonValue], value)


def _request_payload(supplied: GenerationRequest) -> tuple[GenerationRequest, bytes]:
    """Freeze the exact revalidated request bytes before artifact storage or provider I/O."""
    try:
        request = GenerationRequest.model_validate(supplied)
        limits = request.profile.limits
        payload: dict[str, object] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "format": request.response_schema,
            "stream": False,
            "keep_alive": 0,
            # The byte-BPE profile reserves context beyond all serialized bytes and output.
            "options": {
                "temperature": 0,
                "seed": 0,
                "num_ctx": limits.context,
                "num_predict": limits.output,
            },
        }
        if request.model == "qwen3:8b":
            # Freeze non-thinking generation for the bounded model comparison.
            payload["think"] = False
        encoded = _json_bytes(payload)
        if len(encoded) > limits.request_bytes:
            raise ValueError("Model request exceeds its byte limit")
        _check_depth(encoded)
        return request, encoded
    except (ValueError, ValidationError, RecursionError, OverflowError):
        raise ResearchError(
            "MODEL_INPUT_INVALID", "Model request is invalid or exceeds limits.", 422
        ) from None


class OllamaProvider:
    """The existing loopback endpoint is fixed; callers cannot redirect requests or enable tools."""

    def __init__(
        self, *, transport: httpx.BaseTransport | None = None, deadline: float | None = None
    ) -> None:
        """Inject a transport for protocol tests without introducing another SDK or provider."""
        self._transport = transport
        if deadline is not None and (
            type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline < 0
        ):
            raise ValueError("Provider deadline must be a finite monotonic instant")
        self._deadline = deadline

    def _capture(
        self,
        client: httpx.Client,
        path: str,
        payload: bytes | None,
        store: ArtifactStore,
        evidence: _Captures,
        name: str,
        deadline: float,
        read_seconds: int,
    ) -> dict[str, JsonValue]:
        """Bound the retained buffer and archive received prefixes even when transport fails."""
        data = bytearray()
        complete = False
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ResearchError("MODEL_UNAVAILABLE", "Local model time budget expired.", 503)
            with client.stream(
                "POST" if payload is not None else "GET",
                path,
                content=payload,
                timeout=httpx.Timeout(min(read_seconds, remaining), connect=min(3, remaining)),
            ) as response:
                evidence.statuses[name] = response.status_code
                for chunk in response.iter_raw():
                    room = MAX_RESPONSE_BYTES - len(data)
                    data.extend(chunk[:room])
                    if len(chunk) > room:
                        raise ValueError("Provider response exceeds its byte limit")
                    if time.monotonic() >= deadline:
                        raise ResearchError(
                            "MODEL_UNAVAILABLE", "Local model time budget expired.", 503
                        )
                complete = True
                if time.monotonic() >= deadline:
                    raise ResearchError(
                        "MODEL_UNAVAILABLE", "Local model time budget expired.", 503
                    )
                if response.status_code != 200:
                    raise ResearchError("MODEL_UNAVAILABLE", "Local model request failed.", 503)
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ValueError("Unexpected response encoding")
        except httpx.HTTPError:
            raise ResearchError("MODEL_UNAVAILABLE", "Local model request failed.", 503) from None
        finally:
            evidence.complete[name] = complete
            if data or complete:
                evidence.artifacts[name] = store.put(bytes(data), media_type="application/json")
        return _response_object(bytes(data))

    def generate(self, request: GenerationRequest, store: ArtifactStore) -> GenerationResult:
        """Archive one attempt without retries or output repair, returning no unverified success."""
        request, encoded = _request_payload(request)
        limits = request.profile.limits
        request_ref = store.put(encoded, media_type="application/json")
        started = time.monotonic()
        deadline = (
            min(started + 180, self._deadline) if self._deadline is not None else started + 180
        )
        evidence = _Captures()
        digest: str | None = None
        server_version: str | None = None
        parsed: _Response | None = None
        content: str | None = None
        status: Outcome = "malformed"
        try:
            with httpx.Client(
                base_url="http://127.0.0.1:11434",
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(limits.read_seconds, connect=3),
                transport=self._transport,
                headers={"Accept-Encoding": "identity", "Content-Type": "application/json"},
            ) as client:
                inventory = self._capture(
                    client,
                    "/api/tags",
                    None,
                    store,
                    evidence,
                    "inventory",
                    deadline,
                    limits.read_seconds,
                )
                digest = self._digest(inventory, request.model)
                version = self._capture(
                    client,
                    "/api/version",
                    None,
                    store,
                    evidence,
                    "version",
                    deadline,
                    limits.read_seconds,
                )
                value = version.get("version")
                if not isinstance(value, str) or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", value
                ):
                    raise ValueError("Missing or invalid server version")
                server_version = value
                raw = self._capture(
                    client,
                    "/api/chat",
                    encoded,
                    store,
                    evidence,
                    "response",
                    deadline,
                    limits.read_seconds,
                )
                parsed = _Response.model_validate(raw)
                if (
                    not parsed.done
                    or parsed.model != request.model
                    or parsed.eval_count > limits.output
                ):
                    raise ValueError("Provider did not complete the requested model response")
                after = self._capture(
                    client,
                    "/api/tags",
                    None,
                    store,
                    evidence,
                    "inventory_after",
                    deadline,
                    limits.read_seconds,
                )
                if self._digest(after, request.model) != digest:
                    raise ValueError("Model tag changed during generation")
                status = "success" if parsed.done_reason == "stop" else "truncated"
                content = parsed.message.content if status == "success" else None
        except ResearchError as error:
            if error.code != "MODEL_UNAVAILABLE":
                raise
            status = "unavailable"
        except (ValueError, ValidationError, RecursionError, OverflowError):
            status = "malformed"
        record = _CallRecord(
            profile=request.profile,
            status=status,
            model=request.model,
            model_digest=digest,
            server_version=server_version,
            request=request_ref,
            response=evidence.artifacts.get("response"),
            captures=evidence.artifacts,
            capture_complete=evidence.complete,
            http_statuses=evidence.statuses,
            wall_ms=round((time.monotonic() - started) * 1000),
            prompt_tokens=parsed.prompt_eval_count if parsed else None,
            output_tokens=parsed.eval_count if parsed else None,
            provider_duration_ns=parsed.total_duration if parsed else None,
        )
        return GenerationResult(
            status=status,
            content=content,
            record=store.put(
                _json_bytes(record.model_dump(mode="json")), media_type="application/json"
            ),
        )

    @staticmethod
    def _digest(inventory: dict[str, JsonValue], model: str) -> str:
        """Record the installed digest without downloading or repairing missing models."""
        rows = inventory.get("models")
        if not isinstance(rows, list):
            raise ValueError("Missing model inventory")
        matches = [row for row in rows if isinstance(row, dict) and row.get("name") == model]
        if len(matches) != 1:
            raise ResearchError("MODEL_UNAVAILABLE", "Requested local model is unavailable.", 503)
        digest = matches[0].get("digest")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid model digest")
        return digest
