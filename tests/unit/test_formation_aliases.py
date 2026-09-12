"""Reviewed aliases admit only enumerated source wording and retain the original default."""

import json
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.synthesis_fixture import prepare_synthesis_fixture
from factorforge.orchestration.research_strategies import (
    ReviewedStrategyBindingWithAliases,
    approved_formation_rule,
)


@pytest.fixture
def artifacts() -> Iterator[LocalArtifactStore]:
    """Use an owned plain directory without pytest current-directory symlinks on Windows."""
    with TemporaryDirectory() as directory:
        yield LocalArtifactStore(Path(directory))


@pytest.mark.parametrize("wording", ["exact", "period", "extra", "unapproved"])
def test_reviewed_source_aliases(artifacts: LocalArtifactStore, wording: str) -> None:
    """Equivalent descriptions require upfront approval; invented or changed timing stays held."""
    binding = prepare_synthesis_fixture(Path(__file__).resolve().parents[2], artifacts).bindings[0]
    original = binding.reviewed_formation_rule
    extended = (
        original
        + ". Use only signal values available at formation, and trade at the subsequent open."
    )
    reviewed = ReviewedStrategyBindingWithAliases.model_validate_json(
        json.dumps(
            {
                **binding.model_dump(mode="json"),
                "reviewed_formation_rule_aliases": [original + ".", extended],
            }
        )
    )
    observed = {
        "exact": original,
        "period": original + ".",
        "extra": extended,
        "unapproved": "Trade before formation",
    }[wording]
    assert approved_formation_rule(reviewed, observed, artifacts) == (
        original if wording == "unapproved" else observed
    )
    assert approved_formation_rule(binding, observed, artifacts) == original


def test_alias_must_be_in_supplied_source(artifacts: LocalArtifactStore) -> None:
    """Operator approval cannot silently convert an absent source quote into an alias."""
    binding = prepare_synthesis_fixture(Path(__file__).resolve().parents[2], artifacts).bindings[0]
    reviewed = ReviewedStrategyBindingWithAliases.model_validate_json(
        json.dumps(
            {
                **binding.model_dump(mode="json"),
                "reviewed_formation_rule_aliases": ["Trade before formation"],
            }
        )
    )
    with pytest.raises(ValueError, match="source"):
        approved_formation_rule(reviewed, "Trade before formation", artifacts)
