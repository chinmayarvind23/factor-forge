"""Trajectory export preserves attempts and raw answers without turning delivery into rewards."""

import json

import pytest
from test_budgets import NOW, ledger, operation
from test_monthly_admission import MemoryStore

from factorforge.domain.errors import ResearchError
from factorforge.lineage.trajectories import TrajectoryRequest, export_trajectories
from factorforge.orchestration.budgets import reserve, settle


@pytest.mark.parametrize(
    "outcome", ["success", "malformed", "pending", "missing", "nested", "corrupt"]
)
def test_operation_inventory_and_unreviewed_training_status(outcome: str) -> None:
    """Pending attempts stay explicit; valid JSON never grants training approval."""
    store = MemoryStore()
    request_ref = store.put(
        json.dumps(
            {
                "model": "qwen3:8b",
                "messages": [
                    {"role": "system", "content": "Read the source"},
                    {"role": "user", "content": "Untrusted source text"},
                ],
                "format": {"type": "object"},
            }
        ).encode(),
        media_type="application/json",
    )
    response = store.put(
        json.dumps(
            {
                "model": "qwen3:8b",
                "done": True,
                "done_reason": "stop",
                "message": {"role": "assistant", "content": '{"direction":"unknown"}'},
                "prompt_eval_count": 5,
                "eval_count": 4,
                "total_duration": 1,
            }
        ).encode()
        if outcome == "success"
        else b"not json",
        media_type="text/plain",
    )
    provider = store.put(
        json.dumps(
            dict(
                schema_version="local-generation-v2",
                provider="ollama-loopback",
                profile="extraction_32k_v1",
                status="success" if outcome == "success" else "malformed",
                model="qwen3:8b",
                model_digest=None,
                server_version=None,
                request=request_ref.model_dump(),
                response=response.model_dump(),
                captures={},
                capture_complete={},
                http_statuses={},
                wall_ms=1,
                prompt_tokens=5,
                output_tokens=4,
                provider_duration_ns=1,
                billing="local_unmeasured",
            )
        ).encode(),
        media_type="application/json",
    )
    op = operation(cost=1)
    budget, _ = reserve(ledger(), op, at=NOW)
    if outcome != "pending":
        result = (
            store.put(b"{}", media_type="application/json") if outcome == "missing" else provider
        )
        if outcome == "nested":
            previous = json.loads(store.get(provider))
            previous["wall_ms"] = 2
            ancestor = store.put(json.dumps(previous).encode(), media_type="application/json")
            record = store.put(
                json.dumps(
                    {"provider": provider.model_dump(), "request": ancestor.model_dump()}
                ).encode(),
                media_type="application/json",
            )
            result = store.put(
                json.dumps(
                    {
                        "schema_version": "source-synthesis-operation-result-v1",
                        "synthesis": {"record": record.model_dump(), "status": "abstained"},
                    }
                ).encode(),
                media_type="application/json",
            )
        budget = settle(budget, op.operation_id, actual_cost_microusd=None, result=result, at=NOW)
    root = store.put(budget.canonical_bytes(), media_type="application/json")
    if outcome == "corrupt":
        store.values[response.sha256] = b"changed response"
        with pytest.raises(ResearchError):
            export_trajectories(TrajectoryRequest(source=root, partition="development"), store)
        return
    result = export_trajectories(TrajectoryRequest(source=root, partition="development"), store)
    row = json.loads(store.get(result.rows))
    assert row["training_eligibility"] == "unreviewed"
    assert result.operation_count == 1
    assert result.model_attempt_count == int(outcome not in ("pending", "missing"))
    assert result.pending_count == int(outcome == "pending")
    assert result.missing_llm_evidence_count == int(outcome == "missing")
    if outcome in ("success", "malformed"):
        attempt = row["model_attempts"][0]
        assert attempt["messages"][0]["content"] == "Read the source"
        assert attempt["response"] == response.model_dump()
        assert attempt["assistant_content"] == (
            '{"direction":"unknown"}' if outcome == "success" else None
        )
    assert (
        export_trajectories(TrajectoryRequest(source=root, partition="development"), store)
        == result
    )
