"""Untrusted source extraction is a typed observation, not an executable factor strategy."""

import json
import math
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from factorforge.domain.errors import ResearchError

type InputName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")]
type Months = Annotated[int, Field(ge=1, le=120)]
type SourcePage = Annotated[int, Field(ge=1, le=10000)]


class SourceExtraction(BaseModel):
    """Required nullable fields preserve uncertainty; refusal cannot carry a partial strategy."""

    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always"
    )
    status: Literal["extracted", "refused"]
    refusal_reason: Annotated[str, Field(min_length=1, max_length=500)] | None
    refusal_category: Literal["safety", "input_mismatch", "insufficient_information"] | None
    formula: Annotated[str, Field(min_length=1, max_length=2000)] | None
    required_inputs: Annotated[list[InputName], Field(max_length=32)]
    long_short_direction: Literal["long_high_short_low", "long_low_short_high"] | None
    bucket_count: Annotated[int, Field(ge=2, le=100)] | None
    weighting: Literal["equal_weight", "value_weight"] | None
    lookback_months: Months | None
    holding_months: Months | None
    rebalance_frequency: (
        Literal[
            "daily", "weekly", "monthly", "quarterly", "annual_june", "annual_fiscal_year", "annual"
        ]
        | None
    )
    formation_lag_months: Annotated[int, Field(ge=0, le=120)] | None
    formation_rule: Annotated[str, Field(min_length=1, max_length=2000)] | None
    source_pages: Annotated[list[SourcePage], Field(max_length=32)]

    @model_validator(mode="after")
    def coherent_observation(self) -> Self:
        """Reject contradictory terminal states and ambiguous identifiers before later grading."""
        for value in (self.refusal_reason, self.formula, self.formation_rule):
            if value is not None and (
                not value.strip()
                or any(ord(char) < 32 and char not in "\n\r\t" for char in value)
                or "\x7f" in value
            ):
                raise ValueError("Extraction text must be meaningful and portable")
        if len(set(self.required_inputs)) != len(self.required_inputs):
            raise ValueError("Extraction input names must be unique")
        if len(set(self.source_pages)) != len(self.source_pages):
            raise ValueError("Extraction source pages must be unique")
        if self.status == "refused":
            if self.refusal_reason is None or self.refusal_category is None:
                raise ValueError("Refusal requires a reason and category")
            strategy_fields = (
                self.formula,
                self.long_short_direction,
                self.bucket_count,
                self.weighting,
                self.lookback_months,
                self.holding_months,
                self.rebalance_frequency,
                self.formation_lag_months,
                self.formation_rule,
            )
            if any(value is not None for value in strategy_fields) or self.required_inputs:
                raise ValueError("Refusal cannot assert a strategy")
        elif self.refusal_reason is not None or self.refusal_category is not None:
            raise ValueError("Extraction cannot also be a refusal")
        elif not self.source_pages:
            raise ValueError("Extraction requires at least one source page")
        return self


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys before a parser can silently keep only the final value."""
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("Duplicate extraction field")
        values[key] = value
    return values


def _finite_number(value: str) -> float:
    """Ignored fields cannot smuggle nonstandard JSON numbers or overflowing exponents."""
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Nonfinite extraction value")
    return parsed


def parse_extraction(content: str) -> SourceExtraction:
    """Admit one bounded JSON object without repair; raw output stays in provider evidence."""
    try:
        if not isinstance(content, str) or len(content.encode("utf-8")) > 32768:
            raise ValueError("Extraction exceeds its byte limit")
        depth, quoted, escaped = 0, False, False
        for char in content:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                if depth > 16:
                    raise ValueError("Extraction exceeds its depth limit")
            elif char in "]}":
                depth -= 1
        value = json.loads(
            content,
            object_pairs_hook=_unique_pairs,
            parse_float=_finite_number,
            parse_constant=_finite_number,
        )
        return SourceExtraction.model_validate(value)
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise ResearchError(
            "EXTRACTION_INVALID", "Model extraction is invalid or exceeds limits.", 422
        ) from None
