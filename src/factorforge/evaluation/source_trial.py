"""One predeclared source extraction trial retains admission, outcome and grading evidence."""

import argparse
import importlib
import json
import platform
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from pydantic import JsonValue, ValidationError

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.evaluation.cli import _load, _save
from factorforge.evaluation.extraction import GoldCase, grade_extraction
from factorforge.providers.ollama import (
    MAX_REQUEST_BYTES,
    GenerationRequest,
    GenerationResult,
    OllamaProvider,
    _request_payload,
)
from factorforge.retrieval.extraction import (
    PROMPT_VERSION,
    SourcePacket,
    TextProvider,
    extract_source,
    prepare_prompt,
)

CODE_MODULES = (
    "factorforge.evaluation.source_trial",
    "factorforge.evaluation.cli",
    "factorforge.evaluation.extraction",
    "factorforge.retrieval.extraction",
    "factorforge.providers.ollama",
    "factorforge.domain.extraction",
    "factorforge.domain.formula",
    "factorforge.domain.artifacts",
    "factorforge.domain.errors",
    "factorforge.data.artifacts",
)
MAX_SOURCE_BYTES = 1024 * 1024


def _invalid(message: str) -> ResearchError:
    """Trial admission errors omit local filenames, source passages and expected answers."""
    return ResearchError("SOURCE_TRIAL_INVALID", message, 422)


@dataclass(slots=True)
class _FrozenProvider:
    """Recheck the frozen wire bytes at delivery and prevent any second provider invocation."""

    provider: TextProvider
    expected: bytes
    invocations: int = 0

    def generate(self, request: GenerationRequest, store: ArtifactStore) -> GenerationResult:
        """Only the source request reaches delivery; grading data stays in the runner."""
        validated, payload = _request_payload(request)
        if self.invocations or payload != self.expected:
            raise _invalid("Trial request changed or attempted a second delivery.")
        self.invocations += 1
        return self.provider.generate(validated, store)


def _code_and_environment(store: ArtifactStore) -> tuple[dict[str, object], ArtifactRef]:
    """Snapshot installed source before delivery; unsigned bytes do not attest process execution."""
    code: dict[str, object] = {}
    try:
        packages = {
            name: version(name)
            for name in ("factorforge", "pydantic", "pydantic_core", "httpx", "httpcore")
        }
        for name in CODE_MODULES:
            module = importlib.import_module(name)
            if module.__file__ is None:
                raise OSError("Installed source unavailable")
            with Path(module.__file__).open("rb") as source:
                raw = source.read(MAX_SOURCE_BYTES + 1)
            if len(raw) > MAX_SOURCE_BYTES:
                raise OSError("Installed source exceeds limit")
            canonical = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode()
            code[name] = store.put(canonical, media_type="text/x-python").model_dump(mode="json")
    except (ImportError, OSError, UnicodeError):
        raise ResearchError(
            "SOURCE_TRIAL_LINEAGE_INVALID", "Installed source evidence is unavailable.", 503
        ) from None
    environment = _save(
        store,
        {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "packages": packages,
        },
    )
    return code, environment


def run_source_trial(
    packet_path: Path,
    gold_path: Path,
    expected_request_path: Path,
    store: ArtifactStore,
    *,
    provider: TextProvider | None = None,
    model: Literal["llama3.1:8b", "qwen3:8b"] = "llama3.1:8b",
) -> dict[str, object]:
    """Run one admitted case; the caller freezes inputs before observing model output."""
    try:
        packet, packet_raw = _load(packet_path, SourcePacket)
        gold, gold_raw = _load(gold_path, GoldCase)
        expected, pointer_raw = _load(expected_request_path, ArtifactRef)
    except ResearchError:
        raise _invalid("Trial input is unavailable or invalid.") from None
    if (
        packet.paper_id != gold.paper_id
        or packet.source_sha256 != gold.source_sha256
        or {page.pdf_page for page in packet.pages} != set(gold.allowed_source_pages)
    ):
        raise _invalid("Trial source selection does not match the gold case.")
    if expected.size_bytes > MAX_REQUEST_BYTES or expected.media_type != "application/json":
        raise _invalid("Expected request reference exceeds its allowed scope.")
    for page in packet.pages:
        verify_bytes(store.get(page.artifact), page.artifact)
    expected_bytes = store.get(expected)
    verify_bytes(expected_bytes, expected)
    prompt = prepare_prompt(packet, store)
    try:
        request = GenerationRequest(
            model=model,
            system=cast(str, prompt["system"]),
            user=cast(str, prompt["user"]),
            response_schema=cast(dict[str, JsonValue], prompt["response_schema"]),
        )
    except ValidationError:
        raise _invalid("Trial prompt does not satisfy provider admission.") from None
    _, payload = _request_payload(request)
    if payload != expected_bytes:
        raise _invalid("Trial request does not match the frozen expected bytes.")

    code, environment = _code_and_environment(store)
    components = {
        "packet": store.put(packet_raw, media_type="application/json"),
        "gold": store.put(gold_raw, media_type="application/json"),
        "expected_request": expected,
        "expected_request_pointer": store.put(pointer_raw, media_type="application/json"),
        "environment": environment,
    }
    started_at = datetime.now(UTC).isoformat()
    start = _save(
        store,
        {
            "schema_version": "source-trial-start-v1",
            "trial_id": str(uuid4()),
            "case_id": gold.case_id,
            "paper_id": packet.paper_id,
            "started_at": started_at,
            "gold_sha256": gold.sha256,
            "prompt_version": PROMPT_VERSION,
            "text_identity": "utf8-lf-v1",
            "provider_kind": "ollama-loopback" if provider is None else "injected",
            **{name: ref.model_dump(mode="json") for name, ref in components.items()},
            "code": code,
        },
    )
    started = time.perf_counter()
    guarded: _FrozenProvider | None = None
    try:
        guarded = _FrozenProvider(
            provider if provider is not None else OllamaProvider(), expected_bytes
        )
        result = extract_source(packet, guarded, store, model=model)
        store.get(result.record)
        grade = grade_extraction(result.observation, gold, result.status)
        result_ref = _save(store, result.model_dump(mode="json"))
        grade_ref = _save(store, grade.model_dump(mode="json"))
        record = _save(
            store,
            {
                "schema_version": "source-trial-v1",
                "start": start.model_dump(mode="json"),
                "result": result_ref.model_dump(mode="json"),
                "grade": grade_ref.model_dump(mode="json"),
                "provider_invocations": guarded.invocations,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            },
        )
    except BaseException as error:
        # A storage failure may prevent the failure event itself; never hide the original error.
        error.trial_start_record = start  # type: ignore[attr-defined]
        try:
            failure = _save(
                store,
                {
                    "schema_version": "source-trial-failure-v1",
                    "status": "fatal",
                    "start": start.model_dump(mode="json"),
                    "error_code": "SOURCE_TRIAL_EXECUTION_FAILED",
                    "provider_invocations": guarded.invocations if guarded is not None else 0,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                },
            )
            error.trial_failure_record = failure  # type: ignore[attr-defined]
        except Exception:
            error.add_note("Failure event unavailable; the immutable trial-start record remains.")
        raise
    return {
        "record": record.model_dump(mode="json"),
        "start": start.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "grade": grade.model_dump(mode="json"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Use an existing populated store and return safe diagnostics without retry or resume."""
    parser = argparse.ArgumentParser(description="Run one frozen source extraction trial.")
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--expected-request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=("llama3.1:8b", "qwen3:8b"), default="llama3.1:8b")
    args = parser.parse_args(argv)
    try:
        if not args.output.is_dir():
            raise _invalid("Trial output must be an existing owned artifact directory.")
        result = run_source_trial(
            args.packet,
            args.gold,
            args.expected_request,
            LocalArtifactStore(args.output),
            model=args.model,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        details: dict[str, object] = {
            "code": "SOURCE_TRIAL_FAILED",
            "message": "Source trial failed; inspect saved evidence.",
        }
        for attribute in ("trial_start_record", "trial_failure_record"):
            reference = getattr(error, attribute, None)
            if isinstance(reference, ArtifactRef):
                details[attribute] = reference.model_dump(mode="json")
        print(json.dumps({"error": details}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
