"""Optional trusted-operator SQS delivery around the existing durable research workflow."""

import argparse
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.factors import Contract
from factorforge.lineage.closure import verify_closure
from factorforge.orchestration.command import OPERATOR
from factorforge.orchestration.operator_request import OperatorRequest
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.orchestration.report_export import ResearchCompletion
from factorforge.orchestration.research_workflow import ResearchWorkflow


class ResearchJob(Contract):
    """Messages contain retained request identities, never credentials or executable commands."""

    schema_version: Literal["sqs-research-job-v1"] = "sqs-research-job-v1"
    request: ArtifactRef


def request_for(job: ResearchJob, store: LocalArtifactStore) -> OperatorRequest:
    """Verify the full source closure and exact canonical request before dispatch."""
    if job.request.media_type != "application/json" or job.request.size_bytes > 4 * 2**20:
        raise ValueError("Invalid queued request metadata")
    verify_closure(job.request, store)
    raw = store.get(job.request)
    request = OperatorRequest.model_validate_json(raw)
    if request.canonical_bytes() != raw:
        raise ValueError("Queued request must contain canonical bytes")
    return request


class ResearchQueue:
    """FIFO delivery reduces duplicate traffic; PostgreSQL remains execution authority."""

    def __init__(
        self, client: Any, queue_url: str, store: LocalArtifactStore, visibility_seconds: int = 7200
    ) -> None:
        """Keep queue selection operator-configured and require an actual FIFO queue attribute."""
        if not 120 <= visibility_seconds <= 43200:
            raise ValueError("Queue visibility must be 120..43200 seconds")
        if not re.fullmatch(
            r"https://sqs\.[a-z0-9-]+\.amazonaws\.com/[0-9]{12}/[A-Za-z0-9_-]+\.fifo", queue_url
        ):
            raise ValueError("Configure an AWS SQS FIFO queue URL")
        attributes = client.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["FifoQueue"])
        if attributes.get("Attributes", {}).get("FifoQueue") != "true":
            raise ValueError("Research delivery requires a FIFO queue")
        self.client, self.url, self.store = client, queue_url, store
        self.visibility = visibility_seconds

    def submit(self, job: ResearchJob) -> dict[str, str]:
        """Queue one verified request; stable deduplication is supplemented by database replay."""
        request = request_for(job, self.store)
        if request.brief.max_wall_time_s + 60 > self.visibility:
            raise ValueError("Request budget exceeds queue visibility allowance")
        response = self.client.send_message(
            QueueUrl=self.url,
            MessageBody=job.canonical_bytes().decode(),
            MessageGroupId=job.request.sha256,
            MessageDeduplicationId=job.sha256,
        )
        return {"message_id": str(response["MessageId"]), "request_sha256": job.request.sha256}

    def work_once(self, execute: Callable[[OperatorRequest], ArtifactRef]) -> dict[str, object]:
        """Acknowledge verified completion; errors retain the message for reconciliation."""
        response = self.client.receive_message(
            QueueUrl=self.url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=self.visibility,
        )
        messages = response.get("Messages", [])
        if not messages:
            return {"status": "idle"}
        if len(messages) != 1:
            raise ValueError("Unexpected queue receive inventory")
        message = messages[0]
        body = message["Body"]
        if not isinstance(body, str) or len(body.encode()) > 4096:
            raise ValueError("Queued message exceeds contract limit")
        job = ResearchJob.model_validate_json(body)
        request = request_for(job, self.store)
        if request.brief.max_wall_time_s + 60 > self.visibility:
            raise ValueError("Request budget exceeds queue visibility allowance")
        completion_ref = execute(request)
        verify_closure(completion_ref, self.store)
        completion = ResearchCompletion.model_validate_json(self.store.get(completion_ref))
        if completion.request != job.request:
            raise ValueError("Worker completion belongs to a different request")
        self.client.delete_message(QueueUrl=self.url, ReceiptHandle=message["ReceiptHandle"])
        return {"status": "acknowledged", "completion": completion_ref.model_dump(mode="json")}


def main() -> None:
    """Use IAM's normal credential chain; queue access is a trusted operator capability."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-url", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--submit", type=Path, help="Canonical OperatorRequest JSON to enqueue")
    parser.add_argument("--schema", default="factorforge")
    parser.add_argument("--visibility-seconds", type=int, default=7200)
    args = parser.parse_args()
    store = LocalArtifactStore(args.artifacts)
    client = boto3.client(
        "sqs",
        region_name=args.region,
        config=Config(connect_timeout=3, read_timeout=25, retries={"total_max_attempts": 1}),
    )
    queue = ResearchQueue(client, args.queue_url, store, args.visibility_seconds)
    if args.submit is not None:
        with args.submit.open("rb") as source:
            raw = source.read(4 * 2**20 + 1)
        if len(raw) > 4 * 2**20:
            raise ValueError("Request exceeds limit")
        request = OperatorRequest.model_validate_json(raw)
        ref = store.put(request.canonical_bytes(), media_type="application/json")
        print(json.dumps(queue.submit(ResearchJob(request=ref))))
        return
    dsn = os.environ.get("RDS_DSN")
    if not dsn:
        raise ValueError("RDS_DSN is required for the research worker")
    runs = PostgresRunStore(dsn, schema=args.schema)

    def execute(request: OperatorRequest) -> ArtifactRef:
        """Reuse CLI identity, workflow locking, reservations and saved completion."""
        run = runs.create(request.brief, "operator:" + request.sha256, OPERATOR)
        return ResearchWorkflow(runs, run.run_id, OPERATOR, request, store).finish()

    try:
        print(json.dumps(queue.work_once(execute)))
    finally:
        runs.close()


if __name__ == "__main__":
    main()
