"""Transport-fake checks for durable retries, poisoning and finite archived replay."""

import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from replay import DurableJournal, consume, consume_record, event_key, events, produce

from factorforge.domain.raw_market import RawMarketSource


def main() -> None:
    """Exercise real SQLite persistence and Kafka-shaped fakes without claiming broker proof."""
    root = Path(__file__).resolve().parents[2]
    market = RawMarketSource.model_validate_json(
        (root / "data/backtests/monthly-raw-v1/inputs/market.json").read_bytes()
    )
    values = events(market, "a" * 64)
    assert values == events(market, "a" * 64)
    assert values[0].event_id != events(market, "b" * 64)[0].event_id
    event = values[0]
    raw = event.canonical_bytes()
    allowed = {event.event_id: raw}
    record = SimpleNamespace(key=event_key(event), value=raw, topic="test", partition=0, offset=12)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "journal.sqlite3"
        journal = DurableJournal(path)
        consumer = Mock()
        consumer.commit.side_effect = RuntimeError("broker disconnected after durable append")
        try:
            consume_record(consumer, journal, record, allowed)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Expected commit failure")
        journal.close()
        journal = DurableJournal(path)
        consumer.commit.side_effect = None
        assert consume_record(consumer, journal, record, allowed) is False
        assert journal.db.execute("SELECT count(*) FROM quote_events").fetchone()[0] == 1
        offsets = consumer.commit.call_args.args[0]
        assert next(iter(offsets.values())).offset == 13
        consumer.reset_mock()
        record.key = b"tampered"
        try:
            consume_record(consumer, journal, record, allowed)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid key accepted")
        consumer.commit.assert_not_called()
        record.key = event_key(event)
        failed_journal = Mock()
        failed_journal.append.side_effect = OSError("disk unavailable")
        try:
            consume_record(consumer, failed_journal, record, allowed)
        except OSError:
            pass
        else:
            raise AssertionError("Expected journal failure")
        consumer.commit.assert_not_called()
        consumer.poll.return_value = {0: [record]}
        assert consume(consumer, journal, values, 2, time.monotonic() + 2) == {
            "processed": 2,
            "inserted": 0,
        }
        journal.close()
    producer = Mock()
    assert produce(producer, "test", values, 2, time.monotonic() + 2) == 2
    assert producer.send.call_count == 2
    assert produce(producer, "test", values, 2, time.monotonic() - 1) == 0
    print(
        "PASS: stable identities, restart dedupe, offset+1, "
        "invalid-key and disk-failure no-commit, bounded duplicate consumption, bounded producer"
    )


if __name__ == "__main__":
    main()
