"""Allocation templates retain exact partitions without declaring an execution sizing basis."""

from fractions import Fraction

import pytest
from pydantic import ValidationError
from test_targets import panel, portfolio

from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import AllocationSpec
from factorforge.domain.targets import AllocationTemplate, Rational
from factorforge.factors.targets import build_allocation, build_targets


def allocation(**changes: object) -> AllocationSpec:
    """Copy only partition choices, leaving funding conventions to each execution profile."""
    fields = AllocationSpec.model_fields
    return AllocationSpec.model_validate(
        {key: value for key, value in portfolio().model_dump().items() if key in fields} | changes
    )


def test_unit_template_has_no_execution_sizing_claim() -> None:
    """A reusable allocation has its own identity and cannot masquerade as a v2 target plan."""
    result = build_allocation(panel(), allocation(), missing_signal="fail")
    assert result.scope == "unit-sleeve-template"
    assert result.schema_version == "allocation-template-v1"
    assert result.allocation_sha256 == allocation().sha256
    assert "sizing_basis" not in result.canonical_bytes().decode()
    assert [row.weight.as_fraction() for row in result.positions] == (
        [Fraction(-1, 3)] * 3 + [Fraction(0)] * 2 + [Fraction(1, 2)] * 2
    )
    legacy = build_targets(panel(), portfolio(), missing_signal="fail")
    assert legacy.positions == result.positions
    assert legacy.input_sha256 == result.input_sha256
    assert legacy.portfolio_sha256 != result.allocation_sha256
    assert legacy.scope == "conditional-preselected-signal-targets"


@pytest.mark.parametrize(
    "field", ["sizing_basis", "short_proceeds", "long_exposure", "cash_return"]
)
def test_allocation_rejects_execution_fields(field: str) -> None:
    """Unknown funding metadata cannot be carried as an ignored claim on unit templates."""
    with pytest.raises(ValidationError):
        AllocationSpec.model_validate(allocation().model_dump() | {field: "anything"})


def test_template_revalidation_rejects_forged_partition_and_policy() -> None:
    """Saved records must still enforce exact equal weights and the bound policy identity."""
    result = build_allocation(panel(), allocation(), missing_signal="fail")
    bad = result.positions[0].model_copy(update={"weight": Rational.from_fraction(Fraction(-1, 2))})
    for changes in (
        {"positions": (bad, *result.positions[1:])},
        {"allocation_sha256": "0" * 64},
        {"excluded": (result.positions[0].security_id,)},
    ):
        with pytest.raises(ValidationError):
            AllocationTemplate.model_validate(result.model_copy(update=changes))


def test_allocation_handles_value_weights_and_rejects_invalid_copies() -> None:
    """Shared allocation preserves rational capital weights while validating every public input."""
    policy = allocation(weighting="value_weight", weight_input="cap")
    result = build_allocation(panel(), policy, missing_signal="fail")
    assert result.positions[0].weight.as_fraction() == Fraction(-1, 6)
    assert result.positions[-1].weight.as_fraction() == Fraction(2, 3)
    with pytest.raises(ResearchError) as failure:
        build_allocation(
            panel(), policy.model_copy(update={"bucket_count": 0}), missing_signal="fail"
        )
    assert failure.value.code == "ALLOCATION_INPUT_INVALID"


def test_template_exclusions_remain_explicit() -> None:
    """Excluding absent signals remains a predeclared selection policy, not a funding repair."""
    cross_section = panel().model_copy(update={"observations": panel().observations[:-1]})
    result = build_allocation(cross_section, allocation(), missing_signal="exclude_at_formation")
    assert result.excluded == ("G",)
    with pytest.raises(ResearchError):
        build_allocation(cross_section, allocation(), missing_signal="fail")


@pytest.mark.parametrize(
    ("direction", "weighting", "expected_policy", "expected_plan"),
    [
        (
            "long_high_short_low",
            "equal_weight",
            "c69bc3896dbb6b1ffa14a7ff4092fcf418631f20c2cd5cea5e27bf26f43cda30",
            "a7c1343a34a56624104b130b488632615ea26cae70440be908348c6a7928a576",
        ),
        (
            "long_high_short_low",
            "value_weight",
            "9bb0079a30ffba86b47307257732ee5c9142999680bdf860a74148f16113c9ee",
            "0e2f437008245d9cf6529b45c347366e707f5687ca8cc5b378c221f581468f06",
        ),
        (
            "long_low_short_high",
            "equal_weight",
            "777d87200654b26748b11a7ca3d858d8e02a2dc912faa115a05810e5916625d9",
            "805ff419435705297e73a2cced7f07ca020e314250681892f05543887a20304c",
        ),
        (
            "long_low_short_high",
            "value_weight",
            "ae5ac1ca0bfc3d01d03fee9affc295880ed4a4f27119b0100ca94bcd8848e302",
            "ba7fee94493578bcf4471de6b4744bd710bd1d11425478a1c32df7ef3a7314da",
        ),
    ],
)
def test_legacy_contract_bytes_match_pre_refactor_capture(
    direction: str, weighting: str, expected_policy: str, expected_plan: str
) -> None:
    """Hashes captured at a949e71 keep saved v2 policy and target identities replay-compatible."""
    policy = portfolio(
        direction=direction,
        weighting=weighting,
        weight_input="cap" if weighting == "value_weight" else None,
    )
    result = build_targets(panel(), policy, missing_signal="fail")
    assert policy.sha256 == expected_policy
    assert result.sha256 == expected_plan
