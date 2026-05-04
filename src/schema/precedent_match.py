"""
PrecedentMatch / PrecedentMatchResult — output of v3 CBR matching.

Consumed by v6 (report generation) and held in the KnowledgeBase for
downstream agents that may want to reference relevant precedents in v4.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MatchedVia = Literal["primary", "secondary"]


class PrecedentMatch(BaseModel):
    """A single ranked precedent match."""

    precedent_id: str = Field(
        ...,
        description="ID of the matched precedent (e.g. 'PREC-2021-04').",
    )
    accident_type: str = Field(
        ...,
        description="Accident type label of the matched precedent.",
    )
    overlap_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Jaccard overlap of cause_categories: |shared| / |union|.",
    )
    shared_cause_categories: list[str] = Field(
        default_factory=list,
        description="Cause categories present in both the case and the precedent.",
    )
    matched_via: MatchedVia = Field(
        ...,
        description="Whether this precedent matched on v2's primary or secondary type.",
    )


class PrecedentMatchResult(BaseModel):
    """v3's structured output: ranked precedent matches plus funnel telemetry."""

    matches: list[PrecedentMatch] = Field(
        default_factory=list,
        description="Matches sorted by overlap_score descending.",
    )
    primary_type: str = Field(
        ...,
        description="Echo of the v2 primary_type used for the type filter.",
    )
    secondary_types: list[str] = Field(
        default_factory=list,
        description="Echo of the v2 secondary_types used for the type filter.",
    )
    total_precedents: int = Field(
        ...,
        description="Number of precedents considered before filtering.",
    )
    filtered_count: int = Field(
        ...,
        description="Number of precedents that passed the type filter.",
    )
