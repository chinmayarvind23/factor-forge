"""Check source-capture receipts without network calls or research evaluation."""

import hashlib
import io
import json
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError

import pytest

from factorforge.data import yahoo_capture


class Response(io.BytesIO):
    """Expose only the HTTP surface consumed by the capture boundary."""

    status = 200

    def geturl(self) -> str:
        """Retain the final response location in the controlled receipt."""
        return "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"


@pytest.mark.parametrize("scenario", ["captured", "wrong_symbol", "oversized", "forbidden"])
def test_capture_retains_status_and_never_retries(
    scenario: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Access errors stop once; invalid payloads retain an inspectable failure receipt."""
    calls = []
    raw = json.dumps(
        {
            "chart": {
                "error": None,
                "result": [
                    {
                        "meta": {"symbol": "IBM" if scenario == "wrong_symbol" else "AAPL"},
                        "timestamp": [1, 2],
                    }
                ],
            }
        }
    ).encode()
    if scenario == "oversized":
        raw = b"x" * (yahoo_capture.MAX_BYTES + 1)

    def open_response(request: object, timeout: int) -> Response:
        """Fail deterministically without contacting the provider."""
        calls.append(request)
        assert timeout == 30
        if scenario == "forbidden":
            raise HTTPError("https://query1.finance.yahoo.com", 403, "Forbidden", Message(), None)
        return Response(raw)

    monkeypatch.setattr(yahoo_capture, "urlopen", open_response)
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        if scenario == "captured":
            result = yahoo_capture.capture_symbol("AAPL", root)
            assert result["sha256"] == hashlib.sha256(raw).hexdigest()
            assert (root / "AAPL.json").read_bytes() == raw
        else:
            with pytest.raises((ValueError, HTTPError)):
                yahoo_capture.capture_symbol("AAPL", root)
        receipt = json.loads((root / "AAPL.receipt.json").read_bytes())
        assert receipt["status"] == ("captured" if scenario == "captured" else "failed")
        assert "finished_at" in receipt
        if scenario == "forbidden":
            assert receipt["http_status"] == 403
        assert len(calls) == 1
