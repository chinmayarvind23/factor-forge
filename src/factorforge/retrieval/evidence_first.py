"""An experimental extraction profile asks for literal evidence before strategy observations."""

import json
from typing import Annotated, Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field

from factorforge.domain.extraction import SourceExtraction, _unique_pairs, parse_extraction

type StrategyField = Literal[
    "formula",
    "required_inputs",
    "long_short_direction",
    "bucket_count",
    "weighting",
    "lookback_months",
    "holding_months",
    "rebalance_frequency",
    "formation_lag_months",
    "formation_rule",
]


class Quote(BaseModel):
    """A passage may support multiple related fields, keeping the evidence within output limits."""

    model_config = ConfigDict(extra="forbid", strict=True)
    fields: Annotated[list[StrategyField], Field(min_length=1, max_length=10)]
    pdf_page: Annotated[int, Field(ge=1, le=10000)]
    quote: Annotated[str, Field(min_length=1, max_length=1200)]


class EvidenceAnswer(BaseModel):
    """Evidence precedes the observation so the model retrieves before filling fields."""

    model_config = ConfigDict(extra="forbid", strict=True)
    evidence: Annotated[list[Quote], Field(max_length=10)]
    observation: SourceExtraction


def _compact_schema(value: object) -> object:
    """Remove annotation-only schema prose to preserve room for original source passages."""
    if isinstance(value, dict):
        return {
            key: _compact_schema(item)
            for key, item in value.items()
            if key not in {"title", "description"}
        }
    if isinstance(value, list):
        return [_compact_schema(item) for item in value]
    return value


def evidence_prompt(base: dict[str, object]) -> dict[str, object]:
    """Preserve source and field semantics while changing the response protocol explicitly."""
    return {
        **base,
        "system": """First locate the passages defining the SELECTED strategy in the supplied pages.
Return evidence before observation. Copy short exact quotations and their physical pdf_page;
list the strategy fields each quotation supports. Then fill observation from those passages.
Every non-null strategy field and nonempty required_inputs needs quoted support. If a field
is not established by the supplied text, use null (or [] for required_inputs). A single quote
may support several fields. Do not quote the selected_strategy label as if it were source text.
Quotations must come from page text. Return only the requested evidence/observation JSON.
The following field semantics apply to the nested observation:\n"""
        + cast(str, base["system"]),
        "response_schema": _compact_schema(EvidenceAnswer.model_json_schema()),
    }


def parse_evidence(content: str, prompt: dict[str, object]) -> SourceExtraction | None:
    """Check literal membership and field coverage; this does not claim semantic entailment."""
    try:
        if len(content.encode("utf-8")) > 32768:
            return None
        answer = EvidenceAnswer.model_validate(json.loads(content, object_pairs_hook=_unique_pairs))
        observation = parse_extraction(answer.observation.model_dump_json())
        pages = {
            page["pdf_page"]: " ".join(page["text"].split())
            for page in json.loads(cast(str, prompt["user"]))["pages"]
        }
        if not set(observation.source_pages) <= pages.keys():
            return None
        supported = set()
        for quote in answer.evidence:
            text = " ".join(quote.quote.split())
            if (
                not text
                or quote.pdf_page not in observation.source_pages
                or text not in pages[quote.pdf_page]
            ):
                return None
            supported.update(quote.fields)
        asserted = {
            name
            for name, value in observation.model_dump().items()
            if name in get_args(StrategyField.__value__) and value is not None and value != []
        }
        return observation if asserted <= supported else None
    except (ValueError, TypeError, KeyError, RecursionError):
        return None
