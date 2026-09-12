"""Export verified research operation histories as reviewable, provenance-linked JSONL."""

import argparse
import json
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore, reference, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.factors import Contract
from factorforge.factors.hybrid import publish
from factorforge.lineage.closure import verify_closure
from factorforge.orchestration.budgets import BudgetLedger
from factorforge.providers.ollama import _CallRecord, _Response


class TrajectoryRequest(Contract):
    """An explicit caller-declared partition follows the source into every exported row."""

    schema_version: Literal["trajectory-request-v1"] = "trajectory-request-v1"
    source: ArtifactRef
    partition: Literal["development", "evaluation"]


class TrajectoryExport(Contract):
    """Raw attempts stay unreviewed; export assigns no correctness reward and trains no model."""

    schema_version: Literal["trajectory-export-v1"] = "trajectory-export-v1"
    request: TrajectoryRequest
    run_id: UUID
    rows: ArtifactRef
    operation_count: int
    model_attempt_count: int
    pending_count: int
    missing_llm_evidence_count: int
    training_eligibility: Literal["unreviewed"] = "unreviewed"


class _Snapshot:
    """Read each source object once and verify its bytes before retaining the snapshot."""

    def __init__(self, source: ArtifactStore) -> None:
        """Keep the snapshot private to one bounded export, avoiding shared cache authority."""
        self.source = source
        self.values: dict[str, tuple[ArtifactRef, bytes]] = {}

    def get(self, ref: ArtifactRef) -> bytes:
        """Conflicting reference metadata never retrieves bytes from the same digest cache."""
        if ref.sha256 not in self.values:
            raw = self.source.get(ref.model_copy(deep=True))
            verify_bytes(raw, ref)
            self.values[ref.sha256] = (ref, raw)
        expected, raw = self.values[ref.sha256]
        if expected != ref:
            raise ValueError("Conflicting trajectory artifact metadata")
        return raw

    def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Source traversal has no publication capability."""
        raise RuntimeError("Read-only trajectory snapshot")


def _attempt(ref: ArtifactRef, snapshot: _Snapshot) -> dict[str, Any]:
    """Preserve exact prompt text, parseable output text and raw response identity."""
    record = _CallRecord.model_validate_json(snapshot.get(ref))
    wire = json.loads(snapshot.get(record.request))
    messages = wire.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) != 2
        or [row.get("role") for row in messages if isinstance(row, dict)] != ["system", "user"]
        or any(
            set(row) != {"role", "content"} or not isinstance(row["content"], str)
            for row in messages
        )
    ):
        raise ValueError("Unsupported recorded prompt messages")
    assistant = None
    if record.response is not None:
        with suppress(ValidationError):
            assistant = _Response.model_validate_json(snapshot.get(record.response)).message.content
    return dict(
        provider_record=ref.model_dump(),
        request=record.request.model_dump(),
        response=record.response.model_dump() if record.response else None,
        model=record.model,
        model_digest=record.model_digest,
        server_version=record.server_version,
        profile=record.profile.value,
        provider_status=record.status,
        messages=messages,
        response_schema=wire.get("format"),
        assistant_content=assistant,
        prompt_tokens=record.prompt_tokens,
        output_tokens=record.output_tokens,
        wall_ms=record.wall_ms,
        billing=record.billing,
    )


def _operation_attempt(
    result: ArtifactRef, snapshot: _Snapshot, documents: dict[str, Any]
) -> tuple[list[dict[str, Any]], str | None]:
    """Follow the worker's own result edge; input ancestors are not fresh model attempts."""
    wrapper = documents.get(result.sha256, {})
    schema = wrapper.get("schema_version")
    if schema == "local-generation-v2":
        return [_attempt(result, snapshot)], None
    if schema == "planning-step-v1":
        generation = wrapper["generation"]
        return [_attempt(ArtifactRef.model_validate(generation["record"]), snapshot)], generation[
            "status"
        ]
    field = {
        "extraction-operation-result-v1": "extraction",
        "direction-review-operation-result-v1": "direction_review",
        "direction-revision-operation-result-v1": "direction_review",
        "source-synthesis-operation-result-v1": "synthesis",
    }.get(schema)
    if field is None:
        return [], None
    outcome = wrapper[field]
    record = documents[ArtifactRef.model_validate(outcome["record"]).sha256]
    provider = record.get("provider_record", record.get("provider"))
    return (
        [_attempt(ArtifactRef.model_validate(provider), snapshot)] if provider else [],
        outcome.get("status"),
    )


def export_trajectories(request: TrajectoryRequest, artifacts: ArtifactStore) -> TrajectoryExport:
    """Export every budget operation, including pending and uncaptured attempts, without dispatch.

    Delivery status and recorded decisions are observations, not correctness labels.
    Dataset partition is a caller declaration, not proof of benchmark isolation or consent
    for model training. Publication retains the entire source closure through the manifest.
    """
    request = TrajectoryRequest.model_validate(request)
    snapshot = _Snapshot(artifacts)
    refs = verify_closure(request.source, snapshot)
    documents = {
        ref.sha256: json.loads(snapshot.get(ref))
        for ref in refs
        if ref.media_type == "application/json"
    }
    source = documents[request.source.sha256]
    if source.get("schema_version") == "research-budget-v1":
        budget_ref = request.source
    elif source.get("schema_version") in (
        "research-completion-v1",
        "synthesis-research-result-v1",
        "hybrid-experiment-result-v1",
        "deepagents-planning-run-v1",
    ):
        budget_ref = ArtifactRef.model_validate(source["budget"])
    else:
        raise ValueError("A retained research result or budget is required")
    budget = BudgetLedger.model_validate_json(snapshot.get(budget_ref))
    if source.get("run_id") != str(budget.run_id):
        raise ValueError("Source and budget run identities differ")
    rows = []
    attempts_count = missing = pending = 0
    for operation in budget.operations:
        result_ref = operation.observation.result if operation.observation else None
        attempts: list[dict[str, Any]] = []
        decision_status = None
        if result_ref is not None and operation.operation.kind == "llm":
            attempts, decision_status = _operation_attempt(result_ref, snapshot, documents)
        attempts_count += len(attempts)
        pending += int(operation.observation is None)
        missing += int(
            operation.operation.kind == "llm" and result_ref is not None and not attempts
        )
        rows.append(
            dict(
                schema_version="research-trajectory-row-v1",
                source=request.source.model_dump(),
                partition=request.partition,
                training_eligibility="unreviewed",
                run_id=str(budget.run_id),
                operation_id=str(operation.operation.operation_id),
                kind=operation.operation.kind,
                sequence=operation.sequence,
                reserved_at=operation.reserved_at.isoformat(),
                settled_at=operation.observation.at.isoformat() if operation.observation else None,
                operation_status="settled" if operation.observation else "pending",
                root_status=source.get("status"),
                decision_status=decision_status,
                operation_result=result_ref.model_dump() if result_ref else None,
                actual_cost_microusd=operation.observation.actual_cost_microusd
                if operation.observation
                else None,
                model_attempts=attempts,
            )
        )
    raw = b"".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n" for row in rows
    )
    expected = reference(raw, "application/x-ndjson", 8 * 2**20)
    if artifacts.put(raw, media_type=expected.media_type) != expected:
        raise ValueError("Trajectory publication identity differs")
    result = TrajectoryExport(
        request=request,
        run_id=budget.run_id,
        rows=expected,
        operation_count=len(rows),
        model_attempt_count=attempts_count,
        pending_count=pending,
        missing_llm_evidence_count=missing,
    )
    verify_closure(publish(result, artifacts), artifacts)
    return result


def main() -> None:
    """Export local evidence without network access or overwriting an existing dataset file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.request.open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("Trajectory request exceeds limit")
    artifacts = LocalArtifactStore(args.artifacts)
    result = export_trajectories(TrajectoryRequest.model_validate_json(raw), artifacts)
    with args.output.open("xb") as output:
        output.write(artifacts.get(result.rows))
    print(result.model_dump_json())


if __name__ == "__main__":
    main()
