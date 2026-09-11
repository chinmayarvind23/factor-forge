"""The DVC pointer and frozen hand-worked fixture must identify the same bytes on every OS."""

import hashlib
from pathlib import Path


def test_original_fixture_identity_survives_checkout_line_ending_rules() -> None:
    """CRLF conversion once produced a different Linux dataset despite identical JSON values."""
    repository = Path(__file__).parents[2]
    data = (repository / "data/fixtures/tiny-market-v1.json").read_bytes()
    assert len(data) == 8761
    assert hashlib.sha256(data).hexdigest() == (
        "f0f075c544a78fa99ce27dadf615b5fc4d6bd68f0ebe7268591cdcc75ac4e36b"
    )
    pointer = (repository / "data/snapshots/tiny-market-v1.json.dvc").read_text()
    assert f"md5: {hashlib.md5(data, usedforsecurity=False).hexdigest()}" in pointer
    assert f"size: {len(data)}" in pointer
