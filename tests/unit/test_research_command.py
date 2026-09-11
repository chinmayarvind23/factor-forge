"""Operator request validation must precede database setup or provider work."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from factorforge.orchestration.command import main


def test_invalid_request_returns_safe_error(capsys: pytest.CaptureFixture[str]) -> None:
    """Untrusted JSON details are not included in the public command error."""
    with TemporaryDirectory() as directory:
        request = Path(directory) / "request.json"
        request.write_text('{"private-test-content":true}', encoding="utf-8")
        assert (
            main(["--request", str(request), "--artifacts", str(Path(directory) / "objects")]) == 1
        )
    captured = capsys.readouterr()
    assert "OPERATOR_REQUEST_INVALID" in captured.err
    assert "private-test-content" not in captured.err
