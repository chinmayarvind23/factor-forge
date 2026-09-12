"""Capture the fixed historical-study universe into a private, provenance-stamped directory."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SYMBOLS = ("AAPL", "MSFT", "IBM", "JPM", "XOM", "CVX", "WMT", "PG")
MAX_BYTES = 4 * 1024 * 1024


def capture_symbol(symbol: str, output: Path) -> dict[str, object]:
    """Retain response identity and failures without retrying access restrictions."""
    if symbol not in SYMBOLS:
        raise ValueError("Capture supports the predeclared eight-stock study universe")
    query = urlencode(
        {
            "period1": 1262304000,
            "period2": 1735689600,
            "interval": "1d",
            "events": "div,splits",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"
    receipt: dict[str, object] = dict(
        schema_version="yahoo-chart-capture-v1",
        symbol=symbol,
        url=url,
        requested_at=datetime.now(UTC).isoformat(),
        status="started",
        scope="Retrospective historical vintage; local research inputs",
    )
    receipt_path = output / f"{symbol}.receipt.json"
    with receipt_path.open("x", encoding="utf-8") as target:
        json.dump(receipt, target, indent=2)
    try:
        request = Request(
            url, headers={"User-Agent": "FactorForge/0.1", "Accept": "application/json"}
        )
        with urlopen(request, timeout=30) as response:
            receipt["http_status"] = response.status
            receipt["response_url"] = response.geturl()
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Yahoo chart response exceeds 4 MiB")
        receipt.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        with (output / f"{symbol}.json").open("xb") as target:
            target.write(raw)
        payload = json.loads(raw)
        chart = payload["chart"]
        results = chart.get("result")
        if chart.get("error") is not None or not isinstance(results, list) or len(results) != 1:
            raise ValueError("Provider did not return one successful chart")
        if results[0]["meta"]["symbol"] != symbol:
            raise ValueError("Provider chart symbol differs")
        receipt.update(status="captured", bars=len(results[0]["timestamp"]))
        return receipt
    except Exception as error:
        receipt.update(status="failed", error_type=type(error).__name__)
        if isinstance(error, HTTPError):
            receipt["http_status"] = error.code
        raise
    finally:
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")


def capture(output: Path) -> dict[str, object]:
    """Publish bindings only after the complete aligned panel passes the study loader."""
    from factorforge.evaluation.historical_study import load_panel

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipts = [capture_symbol(symbol, output) for symbol in SYMBOLS]
    paths = {symbol: output / f"{symbol}.json" for symbol in SYMBOLS}
    panel, _ = load_panel(paths)
    summary = dict(
        schema_version="historical-source-capture-v1",
        source_rows=panel.height,
        start_date=str(panel["date"].min()),
        end_date=str(panel["date"].max()),
        universe=list(SYMBOLS),
        sources=receipts,
        usage="Retain raw responses locally; review provider terms before sharing data",
    )
    (output / "capture.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output / "sources.json").write_text(
        json.dumps({symbol: str(path) for symbol, path in paths.items()}, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    """Acquire sources only; experiment execution remains a separate explicit command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(capture(args.output)))


if __name__ == "__main__":
    main()
