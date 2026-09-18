"""The DVC pointer and frozen hand-worked fixture must identify the same bytes on every OS."""

import hashlib
from pathlib import Path


def test_original_fixture_identity_survives_checkout_line_ending_rules() -> None:
    """CRLF conversion once produced a different Linux dataset despite identical JSON values."""
    repository = Path(__file__).parents[2]
    data = (repository / "data/fixtures/tiny-market-v1.json").read_bytes()
    assert len(data) == 8761
    assert hashlib.sha256(data).hexdigest() == (
        "9b7064832e4dd5279a399d94cf94281fb3519aee343a05c7b40dbc6178b424de"
    )
    pointer = (repository / "data/snapshots/tiny-market-v1.json.dvc").read_text()
    assert f"md5: {hashlib.md5(data, usedforsecurity=False).hexdigest()}" in pointer
    assert f"size: {len(data)}" in pointer
