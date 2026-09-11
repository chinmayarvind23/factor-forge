"""Single-process development store; the durable PostgreSQL adapter follows this slice."""

from datetime import UTC, datetime
from threading import Lock
from uuid import UUID, uuid4

from factorforge.domain.errors import ResearchError
from factorforge.domain.research_brief import ResearchBrief, RunEvent, RunRecord


class LocalRunStore:
    """Atomic local creation makes HTTP retry behavior explicit before adding a database."""

    def __init__(self, capacity: int = 1000) -> None:
        """Bound local memory; never evict a receipt while a client might retry it."""
        self._runs: dict[UUID, RunRecord] = {}
        self._keys: dict[str, tuple[ResearchBrief, UUID]] = {}
        self._lock = Lock()
        self._capacity = capacity

    def create(self, brief: ResearchBrief, key: str) -> RunRecord:
        """Serialize receipt allocation and reject key reuse with different validated input."""
        with self._lock:
            existing = self._keys.get(key)
            if existing:
                if existing[0] != brief:
                    raise ResearchError(
                        "IDEMPOTENCY_CONFLICT", "This key belongs to a different request.", 409
                    )
                return self._runs[existing[1]]
            if len(self._runs) >= self._capacity:
                raise ResearchError("LOCAL_CAPACITY", "The local run store is full.", 503)
            run_id, created_at = uuid4(), datetime.now(UTC)
            record = RunRecord(
                **brief.model_dump(),
                run_id=run_id,
                status="RECEIVED",
                created_at=created_at,
                events=(RunEvent(status="RECEIVED", created_at=created_at),),
            )
            self._keys[key] = (brief, run_id)
            self._runs[run_id] = record
            return record

    def normalize(self, run_id: UUID) -> None:
        """Idempotent deterministic normalization cannot advance a run into research completion."""
        with self._lock:
            record = self._runs[run_id]
            if record.status != "RECEIVED":
                return
            event = RunEvent(status="BRIEF_NORMALIZED", created_at=datetime.now(UTC))
            self._runs[run_id] = record.model_copy(
                update={
                    "status": "BRIEF_NORMALIZED",
                    "brief": " ".join(record.idea.split()),
                    "events": (*record.events, event),
                }
            )

    def get(self, run_id: UUID) -> RunRecord:
        """Frozen models prevent API consumers from mutating canonical local records."""
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise ResearchError("RUN_NOT_FOUND", "No run exists with that identifier.", 404)
            return record
