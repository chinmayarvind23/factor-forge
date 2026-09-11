"""Input bounds are enforced before state is allocated or any research work starts."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal["RECEIVED", "BRIEF_NORMALIZED"]


class ResearchBrief(BaseModel):
    """The initial budget contract is independent of the later model normalization step."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    idea: str = Field(min_length=3, max_length=4000)
    max_llm_cost_usd: Decimal = Field(default=Decimal("5.00"), gt=0, le=100, decimal_places=2)
    max_wall_time_s: Annotated[int, Field(strict=True, ge=1, le=86400)] = 3600
    max_experiments: Annotated[int, Field(strict=True, ge=1, le=100)] = 12


class RunEvent(BaseModel):
    """Immutable events expose actual state boundaries rather than simulated progress."""

    model_config = ConfigDict(frozen=True)
    status: RunStatus
    created_at: datetime


class RunRecord(ResearchBrief):
    """Local records disclose their persistence mode and do not imply completed research."""

    run_id: UUID
    status: RunStatus
    created_at: datetime
    brief: str | None = None
    events: tuple[RunEvent, ...]
    mode: Literal["local"] = "local"


class RunAccepted(BaseModel):
    """A stable receipt can be replayed even after the stored run advances."""

    run_id: UUID
    status: Literal["RECEIVED"] = "RECEIVED"
