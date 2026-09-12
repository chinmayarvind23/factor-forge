"""Exercise SQS acknowledgement boundaries without cloud calls or research execution."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.orchestration import sqs_jobs
from factorforge.orchestration.report_export import ResearchCompletion


class QueueClient:
    """Record transport calls while preserving the at-least-once receive contract."""

    def __init__(self, body: str) -> None:
        """Retain one controlled message and the observable acknowledgement count."""
        self.body, self.deleted = body, 0

    def get_queue_attributes(self, **kwargs: Any) -> dict[str, Any]:
        """Expose the required FIFO preflight attribute."""
        return {"Attributes": {"FifoQueue": "true"}}

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        """Return the same delivery again if the test repeats processing."""
        assert kwargs["MaxNumberOfMessages"] == 1
        return {"Messages": [{"Body": self.body, "ReceiptHandle": "receipt"}]}

    def delete_message(self, **kwargs: Any) -> None:
        """Count acknowledgement only after verified completion."""
        assert kwargs["ReceiptHandle"] == "receipt"
        self.deleted += 1


@pytest.mark.parametrize("outcome", ["completed", "worker_error", "wrong_request", "bad_body"])
def test_acknowledgement_boundary(outcome: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the successful, source-matching retained completion allows deletion."""
    with TemporaryDirectory() as temporary:
        store = LocalArtifactStore(Path(temporary))
        leaf = store.put(b"{}", media_type="application/json")
        other = store.put(b'{"other":true}', media_type="application/json")
        job = sqs_jobs.ResearchJob(request=leaf)
        client = QueueClient(
            "not JSON" if outcome == "bad_body" else job.canonical_bytes().decode()
        )
        queue = sqs_jobs.ResearchQueue(
            client, "https://sqs.us-east-1.amazonaws.com/123456789012/research.fifo", store
        )
        sentinel = SimpleNamespace(brief=SimpleNamespace(max_wall_time_s=3600))
        monkeypatch.setattr(sqs_jobs, "request_for", lambda job, store: sentinel)

        def execute(request: Any) -> Any:
            """Supply controlled publication evidence; this test launches no research work."""
            assert request is sentinel
            if outcome == "worker_error":
                raise RuntimeError("Interrupted worker")
            completion = ResearchCompletion(
                run_id=UUID(int=1),
                request=other if outcome == "wrong_request" else leaf,
                result=leaf,
                budget=leaf,
                report=leaf,
                markdown=leaf,
            )
            return store.put(completion.canonical_bytes(), media_type="application/json")

        if outcome == "completed":
            assert queue.work_once(execute)["status"] == "acknowledged"
            assert client.deleted == 1
        else:
            with pytest.raises((ValueError, RuntimeError)):
                queue.work_once(execute)
            assert client.deleted == 0
