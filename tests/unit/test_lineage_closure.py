"""Artifact verification rejects broken or ambiguous references before report generation."""

import json

import pytest
from test_monthly_admission import MemoryStore

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.lineage.closure import verify_closure


def test_nested_and_repeated_references_have_one_verified_identity() -> None:
    """Empty original files and repeated references remain valid without extra object reads."""
    store = MemoryStore()
    leaf = store.put(b"", media_type="text/plain")
    root = store.put(
        json.dumps({"nested": [leaf.model_dump(), leaf.model_dump()]}).encode(),
        media_type="application/json",
    )
    assert {ref.sha256 for ref in verify_closure(root, store)} == {root.sha256, leaf.sha256}
    assert store.reads.count(leaf.sha256) == 1


@pytest.mark.parametrize("problem", ["missing", "corrupt", "metadata", "duplicate_key"])
def test_invalid_closure_has_no_successful_receipt(problem: str) -> None:
    """Missing bytes, substitution and ambiguous JSON cannot support verified lineage claims."""
    store = MemoryStore()
    leaf = store.put(b"original", media_type="text/plain")
    refs = [leaf.model_dump()]
    if problem == "missing":
        del store.values[leaf.sha256]
    elif problem == "corrupt":
        store.values[leaf.sha256] = b"modified"
    elif problem == "metadata":
        refs.append(leaf.model_copy(update={"media_type": "application/octet-stream"}).model_dump())
    raw = b'{"same":1,"same":2}' if problem == "duplicate_key" else json.dumps(refs).encode()
    root = store.put(raw, media_type="application/json")
    with pytest.raises(ResearchError) as error:
        verify_closure(root, store)
    assert error.value.code == "LINEAGE_EVIDENCE_INVALID"


def test_oversized_reference_is_rejected_before_read() -> None:
    """An attacker-controlled size cannot cause an unbounded artifact read."""
    store = MemoryStore()
    ref = ArtifactRef(sha256="a" * 64, size_bytes=8 * 2**20 + 1, media_type="text/plain")
    with pytest.raises(ResearchError):
        verify_closure(ref, store)
    assert store.reads == []
