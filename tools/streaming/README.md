# Archived quote replay

This isolated uv project replays the fixed original quotes in an archived `RawMarketSource`.
It is not a live market feed, order router, fill generator, research evaluation or Kafka-to-ledger integration.
Both CLI roles call `admit_monthly` with the current UTC clock to verify the strategy's
source inventory, content hashes and declared local-research rights before connecting.
The consumer accepts only exact canonical messages from that admitted market source.

From the repository root, with an existing local Kafka broker and provisioned topic:

```powershell
uv sync --project tools/streaming --locked
$env:FACTORFORGE_KAFKA_BOOTSTRAP = "localhost:9092"
uv run --project tools/streaming python tools/streaming/verify.py
uv run --project tools/streaming python tools/streaming/replay.py produce --spec data/backtests/monthly-raw-v1/strategy.json --artifacts artifacts/local --max-events 100 --deadline-seconds 30
uv run --project tools/streaming python tools/streaming/replay.py consume --spec data/backtests/monthly-raw-v1/strategy.json --artifacts artifacts/local --journal tools/streaming/quotes.sqlite3 --max-events 100 --deadline-seconds 30
```

`--artifacts` must contain every source object pinned by the chosen strategy; loose JSON
files alone do not pass admission. Topic defaults to `factorforge.archived-quotes.v1`;
`--topic`, `--group`, and `--bootstrap` are explicit overrides. Broker provisioning and
global service configuration are deliberately outside this project.

Event IDs hash the archived market content hash and original quote source ID. Keys bind
source hash and security ID, preserving that security's replay order. Quote timestamps
remain archival timestamps. Producer awaits acknowledgement (`acks=all`) per record.
Consumer disables automatic commits, validates against admitted bytes, and appends to
SQLite with `synchronous=FULL` before committing only that partition's next offset.
A crash after append and before Kafka commit safely retries against the same SQLite
primary key. Conflicting bytes and invalid messages fail closed without committing that
record. The journal stores exact message bytes; downstream economics are not computed.

Use a durable local disk and retain the journal when restarting the same consumer group.
This is at-least-once transport with local deduplication, not distributed exactly-once:
moving a group between machines requires transferring its journal or a shared durable sink.
Processing stops at `max-events` (including duplicates) or its monotonic deadline;
individual in-flight network calls can extend wall time by their configured finite timeout.
Admission and filesystem operations are outside that transport deadline. A rejected record
requires operator correction before resuming, so later offsets are never silently skipped.

`verify.py` uses real temporary SQLite storage and fake transport to test retry after
commit failure, restart dedupe, exact offset commits, disk failure, invalid keys and bounds.
It does not prove broker connectivity, rebalance behavior, replication or power-loss durability.

Client references: [KafkaProducer](https://kafka-python.readthedocs.io/en/2.2.17/apidoc/KafkaProducer.html)
and [KafkaConsumer](https://kafka-python.readthedocs.io/en/2.2.17/apidoc/KafkaConsumer.html).
