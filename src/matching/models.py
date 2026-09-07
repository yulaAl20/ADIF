"""Shared matching types (M3–M7).

The mapping record here is FR-7.3's requirement in code form. Every field it
carries exists because the evaluation needs it: ``deciding_stage`` drives the
ablation attribution (FR-7.8), ``raw_score`` and ``confidence`` are separate
because D6 forbids reporting raw similarity as confidence, and ``alternatives``
feeds both the review UI dropdown (FR-8.3) and the MRR metric (FR-14.7).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Candidate", "MappingRecord", "NO_MAPPING", "Stage"]

NO_MAPPING = "NO_MAPPING"


class Stage(str, Enum):
    """Which mechanism decided a mapping."""

    ALIAS = "alias"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"
    VALUE = "value"
    TEMPLATE = "template"
    NONE = "none"


class Candidate(BaseModel):
    """One proposed CDM target with the score that produced it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cdm_field: str
    raw_score: float = Field(ge=0, le=100)
    stage: Stage
    matched_on: str | None = None


class MappingRecord(BaseModel):
    """The full record of one source column's mapping decision (FR-7.3)."""

    model_config = ConfigDict(extra="forbid")

    source_position: int
    raw_header: str
    normalised_header: str
    target_field: str
    deciding_stage: Stage
    raw_score: float
    confidence: float | None = None
    rank: int = 1
    alternatives: list[Candidate] = Field(default_factory=list)
    conflict_flagged: bool = False
    review_required: bool = False
    notes: str | None = None

    def is_mapped(self) -> bool:
        """True when a CDM target was proposed."""
        return self.target_field != NO_MAPPING
