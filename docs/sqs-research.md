# Optional SQS research delivery

The [SQS adapter](../src/factorforge/orchestration/sqs_jobs.py) queues a retained
`OperatorRequest` and processes one delivery through the existing research workflow.
It does not create infrastructure. AWS execution is unmeasured; four offline transport
checks cover acknowledgement, worker errors, wrong-request completions and malformed
messages. These checks do not measure cloud delivery or research completion rates.

An operator must supply an SQS FIFO queue, IAM permissions, PostgreSQL and a persistent
artifact directory shared by the producer and workers. The queue policy must restrict
senders to trusted research operators: permission to enqueue is permission to request
research under the worker's existing operator identity. This is not a multi-tenant API.
Use a FIFO dead-letter queue and a deliberate redrive policy for malformed or repeatedly
failing jobs. The adapter uses normal boto3 credentials and bounded SDK timeouts.

```powershell
# The producer's artifact store must already contain the request's input closure.
uv run python -m factorforge.orchestration.sqs_jobs --queue-url QUEUE_URL --region us-east-1 --artifacts artifacts/research --submit research-request.json
# Set RDS_DSN in the worker environment; each invocation receives at most one message.
uv run python -m factorforge.orchestration.sqs_jobs --queue-url QUEUE_URL --region us-east-1 --artifacts artifacts/research
```

The message contains a versioned request artifact reference, not an inline prompt or
command. Submission and consumption verify its complete closure and canonical bytes.
The request hash supplies the message group and the existing `operator:` database
idempotency key. FIFO deduplication is only a short transport window; persistent
PostgreSQL workflow receipts remain authoritative after that window expires.

The worker uses the existing LangGraph workflow and PostgreSQL advisory lock. It
checks the returned completion's closure and request identity before deletion. An
execution error, missing artifact, wrong completion or failed delete raises without
acknowledging success. A completed workflow can therefore be replayed if delivery or
acknowledgement is repeated. Existing uncertain model-operation reservations still
require reconciliation; queue redelivery does not authorize another model attempt.

`--visibility-seconds` defaults to 7,200 and accepts 120–43,200 seconds. Submission and
consumption require the research wall-time budget plus 60 seconds to fit that window.
There is no visibility heartbeat. Timeouts are not a distributed execution lock:
unexpected overruns or duplicate deliveries still rely on PostgreSQL serialization.
Operators should monitor queue age, dead-letter traffic and incomplete workflows.
The worker exits after one delivery so a process supervisor owns repetition and restart.

The static Hugging Face dashboard never sends queue messages or holds AWS credentials.
The queue path is optional AWS setup, separate from the free public deployment.
See [AWS visibility and duplicate-delivery semantics](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html).
