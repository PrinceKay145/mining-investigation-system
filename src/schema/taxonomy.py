"""
Taxonomy models - the ID registries everything else references.

Three models: 
CauseCategory: TC_01...TC-13 (technical) and OC-01...OC-10(organizational)
AccidentType - ATD-01...ATD-08
Regulation - REG-01...REG-14

Design notes:
- IDs are validated by regex patten, not hardcoded enums, so adding other categories is easy
- CauseTier is derived from the ID prefic (TC-> Technical, OC-> organizational).
- Supplementary domain knowlege (typical_sources, detection_method, etc.) goes into 'details',
   which keeps the core schema stable across jurisdictions
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator

class CauseTier(str, Enum):
    """Two-tier cause classification used by Rostechnadzor (and most regulators)."""
    TECHNICAL = "technical"
    ORGANIZATIONAL = "organizational"

class CauseCategory(BaseModel):
    """
    A cause category from the regulatory taxonomy

    Examples:
        TC-01 methane_accumulation (technical)
        OC-04 data_falsification (organizational)
    """
    id: str = Field(
        ...,
        pattern = r"^(TC|OC)-\d{2}$",
        description="Category ID: TC-XX for technical, OC-XX for organizational",
    )
    label: str = Field(
        ..., 
        min_length=1,
        description="Snake_case label, e.g. 'methane_accumulation'",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the cause category",
    )
    tier: CauseTier | None = Field(
        default=None,
        description="Derived from ID prefix: set automatically if omitted.",
    )
    details: dict[str, Any]|None = Field(
        default=None, 
        description = "Supplementary domain info (typical_sources, detection_method, etc.)",
    )

    @model_validator(mode="after")
    def _derive_tier(self)-> "CauseCategory":
        if self.tier is None:
            if self.id.startswith("TC-"):
                self.tier = CauseTier.TECHNICAL
            elif self.id.startswith("OC-"):
                self.tier = CauseTier.ORGANIZATIONAL
            else:
                raise ValueError(f"Cannot derive tier from id '{self.id}'")
        return self

class AccidentType(BaseModel):
    """
    An accident type definition from the regulatory taxonomy.

    Examples:
        ATD-01 methane_explosion
        ATD-06 endogenous_fire
    """
    id: str = Field(
        ...,
        pattern = r"^ATD-\d{2}$",
        description="Accident type ID: ATD-XX",
    )
    label: str = Field(
        ...,
        min_length=1,
        description="Snake_case label, e.g. 'methane_explosion'",
    )
    russian_term: str = Field(
        default="",
        description="Russian terminology for cross-referencing source reports",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="What this accident type is and how it works",
    )
    distinguishing_evidence: list[str] = Field(
        default_factory=list,
        description="Evidence patterns that distinguish this type from others",
    )
    key_indicators: list[str] = Field(
        default_factory=list,
        description="Short indicator labels for rule-based classification (v2)",
    )
    common_precursors: list[str] = Field(
        default_factory=list,
        description="Conditions that typically precede this accident type",
    )
    typical_settings: list[str] = Field(
        default_factory=list,
        description="Mine settings where this type typically occurs",
    )

class Regulation(BaseModel):
    """
    A safety regulation summary,

    Regulation summaries (not full texts) - sufficient for the regulatory
    compliance agent to check evidence against requirements.

    Exampels: 
        REG-01  Methane monitoring limits and automatic cutoff
        REG-05  Explosion-proof equipment requirements
    """
    id: str = Field(
        ...,
        pattern=r"^REG-\d{2}$",
        description="Regulation ID: REG-XX",
    )
    topic: str = Field(
        ...,
        min_length=1,
        description="Short topic label",
    )
    requirement: str = Field(
        ...,
        min_length=1,
        description="Summary of what the regulation requires",
    )
    applicable_standard: str = Field(
        default="",
        description="Name of the standard or law this requirement comes from",
    )
    applies_to_accident_types: list[str] = Field(
        default_factory=list,
        description="AccidentType labels this regulation is relevant to (e.g. 'methane_explosion')",
    )
    relevant_cause_categories: list[str] = Field(
        default_factory=list,
        description="CauseCategory IDs this regulation addresses (e.g. 'TC-01', 'OC-04')",
    )
 
    @field_validator("relevant_cause_categories")
    @classmethod
    def _validate_cause_ids(cls, v: list[str]) -> list[str]:
        import re
        pattern = re.compile(r"^(TC|OC)-\d{2}$")
        for cat_id in v:
            if not pattern.match(cat_id):
                raise ValueError(
                    f"Invalid cause category ID '{cat_id}' in relevant_cause_categories. "
                    f"Expected format: TC-XX or OC-XX"
                )
        return v