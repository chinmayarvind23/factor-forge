"""Experimental generation grammar separates supported and uncertain judgment states."""

from typing import Annotated, Any, Literal

from pydantic import Field

from factorforge.domain.factors import Contract


class SupportedDirection(Contract):
    """A supported choice requires both a citation and the absence of uncertainty."""

    direction: Literal["long_high_short_low", "long_low_short_high"]
    quote: Annotated[str, Field(min_length=1, max_length=2000)]
    pdf_page: Annotated[int, Field(ge=1, le=10000)]
    uncertainty: None


class UncertainDirection(Contract):
    """Uncertainty cannot carry a guessed direction or a directional citation."""

    direction: None
    quote: None
    pdf_page: None
    uncertainty: Annotated[str, Field(min_length=1, max_length=1000)]


class DirectionEnvelope(Contract):
    """Disjoint direction values make the two complete wire states unambiguous."""

    judgment: SupportedDirection | UncertainDirection


def direction_envelope_schema() -> dict[str, Any]:
    """Inline the two Pydantic branches for a closed schema without provider ref resolution."""
    schema = DirectionEnvelope.model_json_schema()
    definitions = schema.pop("$defs")
    branches = schema["properties"]["judgment"]["anyOf"]
    schema["properties"]["judgment"]["anyOf"] = [
        definitions[branch["$ref"].removeprefix("#/$defs/")] for branch in branches
    ]
    return schema
