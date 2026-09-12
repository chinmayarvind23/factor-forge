"""Import archived French daily market and risk-free returns as ex-post comparison inputs."""

import argparse
import csv
import io
import json
import platform
import re
import zipfile
import zlib
from datetime import date
from decimal import Decimal, localcontext
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore, reference, verify_bytes
from factorforge.domain.accounting import accounting_context
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.domain.performance import Instant
from factorforge.domain.raw_market import IntervalReturn, IntervalSource
from factorforge.lineage.closure import verify_closure

MEMBER = "F-F_Research_Data_Factors_daily.csv"
LIMIT = 2 * 1024 * 1024


class FrenchDailyRequest(Contract):
    """Pin the source vintage and session clocks; capture gives conservative availability."""

    source: ArtifactRef
    acquisition: ArtifactRef
    retrieved_at: Instant
    session_closes: Annotated[tuple[Instant, ...], Field(min_length=2, max_length=512)]

    @model_validator(mode="after")
    def coherent_scope(self) -> Self:
        """Comparison inputs cannot precede capture or silently combine multiple trading days."""
        if self.source.media_type != "application/zip" or not 0 < self.source.size_bytes <= LIMIT:
            raise ValueError("Daily source must be a bounded ZIP archive")
        if not 0 < self.acquisition.size_bytes <= LIMIT:
            raise ValueError("Acquisition evidence must be bounded and nonempty")
        if self.source.sha256 == self.acquisition.sha256 and self.source != self.acquisition:
            raise ValueError("Conflicting reference metadata")
        if self.session_closes[-1] > self.retrieved_at or any(
            before.date() >= after.date() for before, after in pairwise(self.session_closes)
        ):
            raise ValueError("Session clocks must be ordered distinct dates before capture")
        return self


class FrenchDailyResult(Contract):
    """Published factor returns serve only as reference data, never as a reproduced strategy."""

    schema_version: Literal["french-daily-normalization-v1"] = "french-daily-normalization-v1"
    scope: Literal["ex-post-market-and-risk-free-reference"] = (
        "ex-post-market-and-risk-free-reference"
    )
    request: ArtifactRef
    code: ArtifactRef
    normalized: ArtifactRef
    input_rows: Annotated[int, Field(ge=2, le=50000)]
    emitted_rows: Annotated[int, Field(ge=2, le=1022, multiple_of=2)]


def _publish(store: ArtifactStore, raw: bytes, media: str) -> ArtifactRef:
    """Provider-returned publication identities must agree in hash, size and media type."""
    ref = store.put(raw, media_type=media)
    if ref != reference(raw, media, 64 * 1024 * 1024):
        raise ValueError("Publication identity differs")
    return ref


def _rows(raw: bytes) -> dict[date, tuple[Decimal, Decimal]]:
    """Read one bounded member in memory; strict daily rows prohibit silent repairs or sentinels."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        inventory = archive.infolist()
        if len(inventory) != 1 or inventory[0].filename != MEMBER:
            raise ValueError("Unexpected archive members")
        member = inventory[0]
        if (
            member.flag_bits & 1
            or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
            or not 0 < member.file_size <= 8 * LIMIT
        ):
            raise ValueError("Unsupported archive member")
        with archive.open(member) as stream:
            contents = stream.read(8 * LIMIT + 1)
        if len(contents) != member.file_size or len(contents) > 8 * LIMIT:
            raise ValueError("Expanded archive exceeds declared bound")
    lines = contents.decode("utf-8-sig").splitlines()
    result: dict[date, tuple[Decimal, Decimal]] = {}
    started = False
    ended = False
    previous: date | None = None
    for fields in csv.reader(lines, strict=True):
        fields = [value.strip() for value in fields]
        if not fields or not any(fields):
            continue
        if fields == ["", "Mkt-RF", "SMB", "HML", "RF"]:
            if started:
                raise ValueError("Duplicate daily header")
            started = True
            continue
        if not started:
            continue
        if not re.fullmatch(r"[0-9]{8}", fields[0]):
            # Only the expected copyright trailer is ignored; malformed data is not a footer.
            if len(fields) == 1 and fields[0].startswith("Copyright"):
                ended = True
                continue
            raise ValueError("Unexpected daily record")
        if ended or len(fields) != 5 or len(result) >= 50000:
            raise ValueError("Daily row shape or budget differs")
        day = date(int(fields[0][:4]), int(fields[0][4:6]), int(fields[0][6:8]))
        if previous is not None and day <= previous:
            raise ValueError("Daily dates must be unique and ordered")
        values = []
        for text in fields[1:]:
            if not re.fullmatch(r"-?[0-9]{1,4}(?:\.[0-9]{1,6})?", text):
                raise ValueError("Unexpected return representation")
            value = Decimal(text)
            if value in (Decimal("-99.99"), Decimal("-999")):
                raise ValueError("Missing return sentinel")
            values.append(value)
        with localcontext(accounting_context()):
            market, risk_free = (values[0] + values[3]) / 100, values[3] / 100
        if market < -1 or risk_free < -1:
            raise ValueError("Reference total return below minus one")
        result[day] = market, risk_free
        previous = day
    if not started or len(result) < 2:
        raise ValueError("Daily table is absent or empty")
    return result


def normalize_french_daily(request: FrenchDailyRequest, store: ArtifactStore) -> FrenchDailyResult:
    """Convert complete daily intervals with exact percentage units and retained provenance."""
    try:
        request = FrenchDailyRequest.model_validate(request)
        captured = {}
        for ref in (request.source, request.acquisition):
            raw = store.get(ref.model_copy())
            verify_bytes(raw, ref)
            captured[ref.sha256] = raw
        source = _rows(captured[request.source.sha256])
        if max(source) > request.retrieved_at.date():
            raise ValueError("Source contains dates after capture")
        clocks = request.session_closes
        dates = tuple(at.date() for at in clocks)
        selected = tuple(day for day in source if dates[0] <= day <= dates[-1])
        if selected != dates:
            raise ValueError("Declared sessions differ from the source trading-day inventory")
        rows = []
        for before, after in pairwise(clocks):
            market, risk_free = source[after.date()]
            comparisons: tuple[tuple[Literal["benchmark", "risk_free"], Decimal], ...] = (
                ("benchmark", market),
                ("risk_free", risk_free),
            )
            for series, value in comparisons:
                rows.append(
                    IntervalReturn(
                        source_id=f"french-{series}-{after.date()}",
                        series_id=series,
                        start_at=before,
                        end_at=after,
                        available_at=request.retrieved_at,
                        cumulative_return=value,
                    )
                )
        normalized = IntervalSource(rows=tuple(rows))
        root = Path(__file__).resolve().parents[1]
        files = [
            dict(
                module=name,
                artifact=_publish(store, (root / name).read_bytes(), "text/x-python").model_dump(),
            )
            for name in (
                "data/french_normalizer.py",
                "data/artifacts.py",
                "domain/raw_market.py",
                "domain/accounting.py",
                "domain/performance.py",
                "domain/factors.py",
                "domain/artifacts.py",
            )
        ]
        code = _publish(
            store,
            json.dumps(
                dict(files=files, python=platform.python_version()), sort_keys=True
            ).encode(),
            "application/json",
        )
        result = FrenchDailyResult(
            request=_publish(store, request.canonical_bytes(), "application/json"),
            code=code,
            normalized=_publish(store, normalized.canonical_bytes(), "application/json"),
            input_rows=len(source),
            emitted_rows=len(rows),
        )
        ref = _publish(store, result.canonical_bytes(), "application/json")
        verify_closure(ref, store)
        return result
    except (
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        zipfile.BadZipFile,
        zlib.error,
        EOFError,
        csv.Error,
        RuntimeError,
        NotImplementedError,
    ):
        raise ResearchError(
            "FRENCH_NORMALIZATION_INVALID", "Daily reference normalization failed.", 422
        ) from None


def main() -> None:
    """Run offline from a bounded request and publish without replacing prior evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.request.open("rb") as stream:
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError("Request exceeds byte limit")
    request = FrenchDailyRequest.model_validate_json(raw)
    result = normalize_french_daily(request, LocalArtifactStore(args.artifacts))
    with args.output.open("xb") as stream:
        stream.write(result.canonical_bytes())


if __name__ == "__main__":
    main()
