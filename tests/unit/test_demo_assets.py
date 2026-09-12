"""Demo packaging accepts operator captures without checked-in research outputs."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from scripts.build_space import copy_assets


def test_default_assets_do_not_require_a_report_catalog() -> None:
    """A fresh checkout can package the dashboard without an archived journey capture."""
    with TemporaryDirectory() as folder:
        output = Path(folder)
        copy_assets(output)
        assert (output / "app.js").is_file()
        assert (output / "index.html").is_file()
        assert not (output / "journey.json").exists()
        assert 'href="journey.html"' not in (output / "index.html").read_text()


def test_operator_capture_is_preserved_byte_for_byte() -> None:
    """Packaging preserves the supplied projection rather than replacing it with defaults."""
    with TemporaryDirectory() as folder:
        root = Path(folder)
        capture = root / "capture.json"
        raw = json.dumps(
            {"schema_version": "research-journey-v1", "scope": "Authored input"}
        ).encode()
        capture.write_bytes(raw)
        output = root / "site"
        output.mkdir()
        copy_assets(output, capture)
        assert (output / "journey.json").read_bytes() == raw
        assert (output / "journey.html").is_file()
        assert (output / "journey.js").is_file()


@pytest.mark.parametrize(
    "raw",
    [b"[]", b'{"schema_version":"unknown"}', b"x" * (1024 * 1024 + 1)],
    ids=["array", "unknown-schema", "oversized"],
)
def test_invalid_capture_is_not_published(raw: bytes) -> None:
    """A malformed or oversized external projection cannot become a replay payload."""
    with TemporaryDirectory() as folder:
        root = Path(folder)
        capture = root / "capture.json"
        capture.write_bytes(raw)
        output = root / "site"
        output.mkdir()
        with pytest.raises(ValueError):
            copy_assets(output, capture)
        assert not (output / "journey.json").exists()
