"""Bounded Kafka replay of admitted archived quotes, with durable local deduplication."""

import argparse
import hashlib
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from kafka.structs import OffsetAndMetadata

from factorforge.backtests.admission import admit_monthly
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.factors import Contract, Digest
from factorforge.domain.raw_market import MarketQuote, RawMarketSource
from factorforge.domain.raw_strategy import RawStrategySpec


class QuoteEvent(Contract):
    """Immutable quote envelope binds exact source bytes and the original observation."""

    schema_version: Literal["archived-quote-v1"] = "archived-quote-v1"
    source_sha256: Digest
    event_id: Digest
    quote: MarketQuote


def events(market: RawMarketSource, source_sha256: str) -> tuple[QuoteEvent, ...]:
    """Build stable event IDs independent of transport retries or replay wall clocks."""
    result = []
    for quote in sorted(market.quotes, key=lambda row: (row.observed_at, row.security_id)):
        identity = hashlib.sha256(
            (source_sha256 + ":" + quote.source_id).encode("utf-8")
        ).hexdigest()
        result.append(QuoteEvent(source_sha256=source_sha256, event_id=identity, quote=quote))
    return tuple(result)


def event_key(event: QuoteEvent) -> bytes:
    """Route each source/security sequence to one deterministic Kafka partition key."""
    return f"{event.source_sha256}:{event.quote.security_id}".encode()


def validate_message(key: bytes, raw: bytes, admitted: dict[str, bytes]) -> QuoteEvent:
    """Reject oversized, noncanonical, altered or unadmitted messages before persistence."""
    if not isinstance(raw, bytes) or len(raw) > 16384:
        raise ValueError("Quote message exceeds wire bound")
    event = QuoteEvent.model_validate_json(raw, strict=True)
    if raw != event.canonical_bytes() or admitted.get(event.event_id) != raw:
        raise ValueError("Quote is not an exact admitted event")
    if key != event_key(event):
        raise ValueError("Quote partition key differs from admitted source/security")
    return event


class DurableJournal:
    """SQLite FULL synchronous commits append observations and dedupe in one transaction."""

    def __init__(self, path: Path) -> None:
        """Open a local journal; unique event IDs survive consumer restarts."""
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS quote_events "
            "(event_id TEXT PRIMARY KEY, payload BLOB NOT NULL)"
        )
        self.db.commit()

    def append(self, event: QuoteEvent, raw: bytes) -> bool:
        """Durably append once, rejecting any identity collision with different bytes."""
        with self.db:
            old = self.db.execute(
                "SELECT payload FROM quote_events WHERE event_id=?", (event.event_id,)
            ).fetchone()
            if old is not None:
                if old[0] != raw:
                    raise ValueError("Journal event identity conflict")
                return False
            self.db.execute("INSERT INTO quote_events VALUES (?, ?)", (event.event_id, raw))
        return True

    def close(self) -> None:
        """Release the durable journal connection."""
        self.db.close()


def consume_record(consumer, journal: DurableJournal, record, admitted: dict[str, bytes]) -> bool:
    """Commit only this processed offset after durable append, never a prefetched batch."""
    event = validate_message(record.key, record.value, admitted)
    inserted = journal.append(event, record.value)
    consumer.commit(
        {
            TopicPartition(record.topic, record.partition): OffsetAndMetadata(
                record.offset + 1, "", -1
            )
        },
        timeout_ms=3000,
    )
    return inserted


def produce(
    producer, topic: str, values: tuple[QuoteEvent, ...], maximum: int, deadline: float
) -> int:
    """Await broker acknowledgement per event and stop at a finite count or monotonic deadline."""
    count = 0
    for event in values[:maximum]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        producer.send(topic, key=event_key(event), value=event.canonical_bytes()).get(
            timeout=remaining
        )
        count += 1
    return count


def consume(
    consumer, journal: DurableJournal, values: tuple[QuoteEvent, ...], maximum: int, deadline: float
) -> dict[str, int]:
    """Count processed records including retries so duplicates cannot defeat the finite budget."""
    admitted = {event.event_id: event.canonical_bytes() for event in values}
    processed = inserted = 0
    while processed < maximum and time.monotonic() < deadline:
        batch = consumer.poll(
            timeout_ms=max(1, min(500, int((deadline - time.monotonic()) * 1000))), max_records=1
        )
        for records in batch.values():
            for record in records:
                if processed >= maximum or time.monotonic() >= deadline:
                    return {"processed": processed, "inserted": inserted}
                inserted += consume_record(consumer, journal, record, admitted)
                processed += 1
    return {"processed": processed, "inserted": inserted}


def main() -> None:
    """Re-admit archived source rights and bytes before opening either Kafka role."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("produce", "consume"))
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--journal", type=Path, default=Path("quotes.sqlite3"))
    parser.add_argument(
        "--bootstrap", default=os.getenv("FACTORFORGE_KAFKA_BOOTSTRAP", "localhost:9092")
    )
    parser.add_argument("--topic", default="factorforge.archived-quotes.v1")
    parser.add_argument("--group", default="factorforge-quote-archive-v1")
    parser.add_argument("--max-events", type=int, default=100)
    parser.add_argument("--deadline-seconds", type=float, default=30)
    args = parser.parse_args()
    if not 1 <= args.max_events <= 8192 or not 0 < args.deadline_seconds <= 3600:
        parser.error("max-events must be 1..8192 and deadline-seconds must be (0, 3600]")
    spec = RawStrategySpec.model_validate_json(args.spec.read_bytes(), strict=True)
    admission = admit_monthly(
        spec, LocalArtifactStore(args.artifacts), evaluated_at=datetime.now(UTC)
    )
    values = events(admission.market, admission.receipt.market_ref.sha256)
    deadline = time.monotonic() + args.deadline_seconds
    common = {
        "bootstrap_servers": args.bootstrap,
        "api_version_auto_timeout_ms": 3000,
        "request_timeout_ms": 10000,
    }
    if args.mode == "produce":
        producer = KafkaProducer(
            **common,
            acks="all",
            retries=3,
            max_in_flight_requests_per_connection=1,
            max_block_ms=3000,
        )
        try:
            print(
                {"acknowledged": produce(producer, args.topic, values, args.max_events, deadline)}
            )
        finally:
            producer.close(timeout=3)
    else:
        consumer = KafkaConsumer(
            args.topic,
            **common,
            group_id=args.group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            session_timeout_ms=6000,
            heartbeat_interval_ms=2000,
        )
        journal = DurableJournal(args.journal)
        try:
            print(consume(consumer, journal, values, args.max_events, deadline))
        finally:
            journal.close()
            consumer.close(autocommit=False, timeout_ms=3000)


if __name__ == "__main__":
    main()
