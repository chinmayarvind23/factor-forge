"""Shared bounded, read-only access to operator-supplied historical evidence."""

import hashlib
import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]
FILES = {
    "historical-study": "historical-study-v1.json",
    "historical-freeze": "evidence/historical-freeze.json",
    "historical-manifest": "evidence/historical-manifest.json",
    "historical-mlflow": "evidence/historical-mlflow.json",
    "historical-mlflow-replay": "evidence/historical-mlflow-replay.json",
    "redis-discovery": "evidence/redis-discovery.json",
    "spark-materialization": "evidence/spark-materialization.json",
}
MAX_BYTES = 1_000_000


class Experiment(BaseModel):
    """Validate exposed metrics without recomputing financial evidence."""

    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    signal: str = Field(max_length=200)
    cost_bps: int = Field(ge=0)
    status: str = Field(max_length=100)
    n: int = Field(ge=0)
    annualized_sharpe: float | None
    total_return: float | None
    max_drawdown: float | None
    hac_t: float | None


class Study(BaseModel):
    """Keep the original scope alongside every summary of saved experiments."""

    model_config = ConfigDict(strict=True)
    scope: str
    source_rows: int = Field(ge=0)
    source_count: int = Field(ge=0)
    start_date: str
    end_date: str
    experiments: list[Experiment] = Field(max_length=1000)


def read_evidence(evidence_id: str) -> dict:
    """Resolve only an allowlisted file; reject symlink escape and oversized JSON."""
    if evidence_id not in FILES:
        raise ValueError("Unknown evidence ID")
    reports = Path(os.environ.get("FACTORFORGE_REPORTS_DIR", ROOT / "artifacts/reports")).resolve()
    path = (reports / FILES[evidence_id]).resolve()
    if not path.is_relative_to(reports):
        raise ValueError("Evidence path escaped reports")
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Evidence exceeds size limit")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Evidence must be a JSON object")
    if evidence_id == "historical-study":
        Study.model_validate(payload)
    elif evidence_id == "historical-manifest":
        if not payload or not all(
            isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
            for value in payload.values()
        ):
            raise ValueError("Manifest must map artifact names to SHA-256 digests")
    elif not isinstance(payload.get("schema_version"), str):
        raise ValueError("Receipt requires schema_version")
    return {"id": evidence_id, "sha256": hashlib.sha256(raw).hexdigest(), "payload": payload}


def study() -> Study:
    """Both transports use the same typed validation boundary."""
    return Study.model_validate(read_evidence("historical-study")["payload"])


def experiments(limit: int = 20, offset: int = 0) -> list[dict]:
    """Bound each page and reject invalid ranges rather than silently truncating."""
    if (
        type(limit) is not int
        or type(offset) is not int
        or not 1 <= limit <= 100
        or not 0 <= offset <= 1000
    ):
        raise ValueError("limit must be 1..100 and offset 0..1000")
    return [item.model_dump() for item in study().experiments[offset : offset + limit]]
