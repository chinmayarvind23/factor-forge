"""One budgeted source-extraction delivery preserves prompts, observations and replay identity."""

import hashlib
import time
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import Field

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Digest
from factorforge.orchestration.budgets import Operation
from factorforge.orchestration.postgres_budgets import reserve_operation, settle_operation
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.providers.ollama import OllamaProvider
from factorforge.retrieval.extraction import (
    SYSTEM_PROMPT,
    ExtractionResult,
    SourcePacket,
    extract_source,
)

PROMPT_SHA256 = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()


class ExtractionCommand(Contract):
    """A captured source, fixed provider profile and prompt identity define one model attempt."""

    schema_version: Literal["extraction-command-v1"] = "extraction-command-v1"
    profile: Literal["ollama-llama3.1-8b-extraction-32k-v1"] = (
        "ollama-llama3.1-8b-extraction-32k-v1"
    )
    prompt_sha256: Digest = PROMPT_SHA256
    source: SourcePacket
    max_cost_microusd: Annotated[int, Field(ge=1, le=100000000)]


class ExtractionOperationResult(Contract):
    """The durable result binds the exact worker command to the extractor's full evidence record."""

    schema_version: Literal["extraction-operation-result-v1"] = "extraction-operation-result-v1"
    command: ExtractionCommand
    extraction: ExtractionResult


def execute_extraction_operation(
    runs: PostgresRunStore,
    run_id: UUID,
    principal: Principal,
    command: ExtractionCommand,
    artifacts: ArtifactStore,
) -> ExtractionResult:
    """Reserve before the fixed local provider call and settle with explicitly unknown dollar cost.

    Ollama's delivery record does not report a dollar bill. Unknown charge retains the full
    reservation rather than treating local execution as measured zero-cost inference. A retry
    of the exact command recovers its original result, including refusals and delivery failures.
    """
    principal.require("execute_research")
    command = ExtractionCommand.model_validate(command)
    if command.prompt_sha256 != PROMPT_SHA256:
        raise ResearchError(
            "EXTRACTION_PROFILE_UNSUPPORTED", "The extraction profile is unavailable.", 409
        )
    operation = Operation(
        operation_id=uuid5(run_id, "extraction-worker-v1:" + command.sha256),
        kind="llm",
        request_sha256=command.sha256,
        max_cost_microusd=command.max_cost_microusd,
    )
    monotonic_start, assessed_at = time.monotonic(), datetime.now(UTC)
    ledger, dispatch = reserve_operation(runs, run_id, principal, operation, at=assessed_at)
    if not dispatch:
        reserved = next(row for row in ledger.operations if row.operation == operation)
        if reserved.observation is None:
            raise ResearchError(
                "RESEARCH_OPERATION_UNRESOLVED", "The recorded operation needs reconciliation.", 409
            )
        return _recover(artifacts, reserved.observation.result, command)
    runs._inject("after_extraction_reservation")
    remaining = max(0.0, (ledger.deadline - assessed_at).total_seconds())
    extracted = extract_source(
        command.source, OllamaProvider(deadline=monotonic_start + remaining), artifacts
    )
    result = ExtractionOperationResult(command=command, extraction=extracted)
    raw = result.canonical_bytes()
    expected = ArtifactRef(
        sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), media_type="application/json"
    )
    if len(raw) > 2**20 or artifacts.put(raw, media_type="application/json") != expected:
        raise ResearchError(
            "RESEARCH_RESULT_INVALID", "The extraction result cannot be verified.", 409
        )
    runs._inject("before_extraction_settlement")
    settle_operation(
        runs,
        run_id,
        principal,
        operation.operation_id,
        result=expected,
        artifacts=artifacts,
        actual_cost_microusd=None,
        at=datetime.now(UTC),
    )
    return extracted


def _recover(
    artifacts: ArtifactStore, ref: ArtifactRef, command: ExtractionCommand
) -> ExtractionResult:
    """Validate immutable output bytes and their exact source/profile binding before reuse."""
    try:
        if ref.size_bytes > 2**20 or ref.media_type != "application/json":
            raise ValueError("Unsupported extraction result envelope")
        raw = artifacts.get(ref.model_copy(deep=True))
        if (
            type(raw) is not bytes
            or len(raw) != ref.size_bytes
            or hashlib.sha256(raw).hexdigest() != ref.sha256
        ):
            raise ValueError("Result byte mismatch")
        parsed = ExtractionOperationResult.model_validate_json(raw)
        if parsed.canonical_bytes() != raw or parsed.command != command:
            raise ValueError("Extraction command mismatch")
        return parsed.extraction
    except Exception:
        raise ResearchError(
            "RESEARCH_RESULT_INVALID", "The extraction result cannot be verified.", 409
        ) from None
