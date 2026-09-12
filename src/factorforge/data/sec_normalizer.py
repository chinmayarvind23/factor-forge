"""Normalize archived SEC company-concept facts using explicitly reviewed accession timing."""

import argparse
import json
import platform
import re
from datetime import UTC, date, datetime
from decimal import Decimal, DecimalException
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore, reference, verify_bytes
from factorforge.data.point_in_time import FundamentalFact
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Identifier
from factorforge.domain.monthly_signals import MonthlySourceBundle, revalidated_fact
from factorforge.lineage.closure import verify_closure

ACCESSION = r"[0-9]{10}-[0-9]{2}-[0-9]{6}"


class FilingAvailability(Contract):
    """Reviewed public availability cites evidence; a filed date alone is insufficient."""

    accession: Annotated[str, Field(pattern="^" + ACCESSION + "$")]
    available_at: AwareDatetime
    evidence: ArtifactRef

    @field_validator("available_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        """Equivalent offsets serialize identically for repeatable source interpretation."""
        return value.astimezone(UTC)


class SecNormalizationRequest(Contract):
    """Freeze source, unit, period scope and reviewed entity-to-security interpretation."""

    source: ArtifactRef
    cik: Annotated[str, Field(pattern=r"^[0-9]{10}$")]
    taxonomy: Literal["us-gaap", "ifrs-full"]
    tag: Identifier
    unit: Literal["USD", "shares", "pure"]
    period_kind: Literal["instant", "duration"]
    security_id: Identifier
    security_mapping: ArtifactRef
    retrieved_at: AwareDatetime
    filed_from: date
    filed_through: date
    availability: Annotated[tuple[FilingAvailability, ...], Field(max_length=128)]

    @field_validator("retrieved_at")
    @classmethod
    def utc_capture(cls, value: datetime) -> datetime:
        """Capture time uses the same absolute clock as reviewed public availability."""
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bounded_request(self) -> Self:
        """Preflight all referenced evidence before storage access or source parsing."""
        if self.filed_from > self.filed_through or len(
            {r.accession for r in self.availability}
        ) != len(self.availability):
            raise ValueError("Filing window or timing inventory is ambiguous")
        if self.filed_through > self.retrieved_at.date() or any(
            row.available_at > self.retrieved_at for row in self.availability
        ):
            raise ValueError("Filing window and reviewed availability must precede capture")
        if (
            self.source.media_type != "application/json"
            or not 0 < self.source.size_bytes <= 2 * 1024 * 1024
        ):
            raise ValueError("SEC concept response must be bounded JSON")
        refs: dict[str, ArtifactRef] = {}
        for ref in (self.source, self.security_mapping, *(r.evidence for r in self.availability)):
            if ref.sha256 in refs and refs[ref.sha256] != ref:
                raise ValueError("Conflicting evidence reference")
            if ref.size_bytes <= 0:
                raise ValueError("Empty evidence cannot support a source mapping")
            refs[ref.sha256] = ref
        if len(refs) > 128 or sum(r.size_bytes for r in refs.values()) > 64 * 1024 * 1024:
            raise ValueError("Normalization evidence exceeds its budget")
        return self


class SecNormalizationResult(Contract):
    """A held result retains evidence but emits no partially timed normalized source."""

    schema_version: Literal["sec-normalization-v1"] = "sec-normalization-v1"
    request: ArtifactRef
    code: ArtifactRef
    status: Literal["ready", "held"]
    reason: Literal["missing_timing", "empty_window"] | None
    input_rows: Annotated[int, Field(ge=0, le=50000)]
    selected_rows: Annotated[int, Field(ge=0, le=50000)]
    emitted_rows: Annotated[int, Field(ge=0, le=50000)]
    unresolved_accessions: Annotated[
        tuple[Annotated[str, Field(pattern="^" + ACCESSION + "$")], ...], Field(max_length=50000)
    ]
    normalized: ArtifactRef | None

    @model_validator(mode="after")
    def coherent_inventory(self) -> Self:
        """Held output cannot impersonate a complete conversion or conceal omitted scoped rows."""
        if not 0 <= self.emitted_rows <= self.selected_rows <= self.input_rows:
            raise ValueError("Normalization row counts are inconsistent")
        if self.unresolved_accessions != tuple(sorted(set(self.unresolved_accessions))):
            raise ValueError("Unresolved accession inventory must be unique and sorted")
        if self.status == "ready":
            if (
                self.reason is not None
                or self.normalized is None
                or self.unresolved_accessions
                or self.emitted_rows != self.selected_rows
                or self.emitted_rows == 0
            ):
                raise ValueError("Ready normalization must account for every selected row")
        elif (
            self.normalized is not None
            or self.emitted_rows != 0
            or not (
                (
                    self.reason == "missing_timing"
                    and self.unresolved_accessions
                    and self.selected_rows > 0
                )
                or (
                    self.reason == "empty_window"
                    and not self.unresolved_accessions
                    and self.selected_rows == 0
                )
            )
        ):
            raise ValueError("Held normalization must expose its unresolved scope")
        return self


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Duplicate JSON keys cannot silently replace entity identity or reported fact values."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate SEC JSON key")
        result[key] = value
    return result


def _publish(store: ArtifactStore, raw: bytes, media_type: str) -> ArtifactRef:
    """Retained normalization evidence independently checks the provider's returned identity."""
    ref = store.put(raw, media_type=media_type)
    if ref != reference(raw, media_type, 64 * 1024 * 1024):
        raise ValueError("Normalization publication identity differs")
    return ref


def _code(store: ArtifactStore) -> ArtifactRef:
    """Capture normalization and validation source plus actual interpreter/package versions."""
    root = Path(__file__).resolve().parents[1]
    files = [
        dict(
            module=name,
            artifact=_publish(store, (root / name).read_bytes(), "text/x-python").model_dump(),
        )
        for name in (
            "data/sec_normalizer.py",
            "data/point_in_time.py",
            "data/artifacts.py",
            "domain/monthly_signals.py",
            "domain/factors.py",
            "domain/artifacts.py",
        )
    ]
    return _publish(
        store,
        json.dumps(
            dict(files=files, python=platform.python_version(), pydantic=version("pydantic")),
            sort_keys=True,
        ).encode(),
        "application/json",
    )


def normalize_sec(request: SecNormalizationRequest, store: ArtifactStore) -> SecNormalizationResult:
    """Preserve every scoped filing revision and require evidence before assigning availability.

    CIK denotes an entity, not a tradable share class. The security mapping and accession
    timing are trusted ingestion inputs; their hashes establish identity, not semantic truth.
    """
    try:
        request = SecNormalizationRequest.model_validate(request)
        captured: dict[str, bytes] = {}
        for ref in (
            request.source,
            request.security_mapping,
            *(r.evidence for r in request.availability),
        ):
            if ref.sha256 not in captured:
                raw = store.get(ref.model_copy())
                verify_bytes(raw, ref)
                captured[ref.sha256] = raw
        source = json.loads(
            captured[request.source.sha256].decode("utf-8"),
            parse_float=Decimal,
            object_pairs_hook=_object,
        )
        if (
            type(source["cik"]) is not int
            or source["cik"] != int(request.cik)
            or source["taxonomy"] != request.taxonomy
            or source["tag"] != request.tag
        ):
            raise ValueError("SEC source identity differs from the request")
        rows = source["units"][request.unit]
        if not isinstance(rows, list) or len(rows) > 50000:
            raise ValueError("SEC unit rows exceed bounds")
        selected = []
        for row in rows:
            filed = date.fromisoformat(row["filed"])
            if request.filed_from <= filed <= request.filed_through:
                if not isinstance(row["accn"], str) or re.fullmatch(ACCESSION, row["accn"]) is None:
                    raise ValueError("Invalid SEC accession")
                selected.append((row, filed))
        timing = {r.accession: r for r in request.availability}
        missing = tuple(sorted({row["accn"] for row, _ in selected} - timing.keys()))
        facts = []
        seen: dict[tuple[str, date | None, date], FundamentalFact] = {}
        if not missing:
            for row, filed in selected:
                start = date.fromisoformat(row["start"]) if "start" in row else None
                if (start is None) != (request.period_kind == "instant"):
                    raise ValueError("Reported period kind differs from the request")
                value = row["val"]
                if type(value) not in (int, Decimal) or len(str(value)) > 128:
                    raise ValueError("SEC values require bounded exact numeric tokens")
                available = timing[row["accn"]].available_at
                if available.date() < filed:
                    raise ValueError("Reviewed availability precedes the SEC filed date")
                fact = revalidated_fact(
                    FundamentalFact(
                        security_id=request.security_id,
                        concept=f"{request.taxonomy}:{request.tag}",
                        period_start=start,
                        period_end=date.fromisoformat(row["end"]),
                        value=Decimal(value),
                        unit="dimensionless" if request.unit == "pure" else request.unit,
                        available_at=available,
                        source_id="sec:" + row["accn"],
                    )
                )
                key = fact.source_id, start, fact.period_end
                if key in seen and seen[key] != fact:
                    raise ValueError("Conflicting values within one SEC filing context")
                seen[key] = fact
                facts.append(fact)
        normalized = (
            _publish(
                store,
                MonthlySourceBundle(facts=tuple(facts), membership=()).canonical_bytes(),
                "application/json",
            )
            if facts
            else None
        )
        result = SecNormalizationResult(
            request=_publish(store, request.canonical_bytes(), "application/json"),
            code=_code(store),
            status="ready" if normalized else "held",
            reason="missing_timing" if missing else "empty_window" if not selected else None,
            input_rows=len(rows),
            selected_rows=len(selected),
            emitted_rows=len(facts),
            unresolved_accessions=missing,
            normalized=normalized,
        )
        verify_closure(_publish(store, result.canonical_bytes(), "application/json"), store)
        return result
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, DecimalException):
        raise ResearchError(
            "SEC_NORMALIZATION_INVALID", "SEC source normalization failed validation.", 422
        ) from None


def main() -> None:
    """Normalize an already archived response; no network requests or inferred permissions occur."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.request.open("rb") as source:
        raw = source.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError("SEC request exceeds byte limit")
    request = SecNormalizationRequest.model_validate_json(raw)
    with args.output.open("xb") as destination:
        result = normalize_sec(request, LocalArtifactStore(args.artifacts))
        destination.write(result.canonical_bytes())
    print(json.dumps(dict(status=result.status, emitted_rows=result.emitted_rows)))


if __name__ == "__main__":
    main()
