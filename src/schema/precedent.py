"""
Precedent models — accident case records for CBR matching (v3).

Two models:
  SimilarityProfile  — 24 typed flags enabling Jaccard-style matching
  Precedent          — full case record wrapping the profile

Design notes:
  - SimilarityProfile is strict Pydantic: every flag is explicitly typed.
    Adding a new flag = one line addition. Typos caught at load time.
  - bool | None flags use None to mean "unknown / not determined" —
    distinct from False ("confirmed absent"). v3 matching skips None
    fields when computing overlap.
  - violated_regulations stores REG-XX IDs; referential integrity is
    checked at the KB loader level, not here (decision #2).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# SimilarityProfile
# ---------------------------------------------------------------------------

class IgnitionType(str, Enum):
    """Known ignition source categories from the taxonomy."""
    NONE = "none"               # no ignition (e.g. outburst, rock burst)
    UNKNOWN = "unknown"         # ignition occurred but source not identified
    MECHANICAL = "mechanical"   # TC-02: AFC chain, shearer, grinder
    ELECTRICAL = "electrical"   # TC-03: arcing, cable damage
    CHEMICAL = "chemical"       # TC-04: reagents, spontaneous combustion, hot work


class DataCompleteness(str, Enum):
    """How much detail is available for this precedent."""
    FULL = "full"
    PARTIAL = "partial"
    MINIMAL = "minimal"


class SimilarityProfile(BaseModel):
    """
    24 typed flags describing an accident's characteristics.

    Used by v3 (precedent matching) for Jaccard cause-category overlap
    and by agents for pattern recognition. Each bool | None flag means:
      True  = confirmed present
      False = confirmed absent
      None  = unknown / not determined (skipped in matching)
    """

    # --- Setting ---
    accident_type: str = Field(
        ..., description="AccidentType label (e.g. 'methane_explosion', 'unknown')"
    )
    work_type: str = Field(
        ..., description="e.g. 'underground_extraction', 'open_pit', 'unknown'"
    )
    underground: bool | None = Field(
        ..., description="Whether accident occurred underground"
    )

    # --- Hazard flags ---
    longwall_face_involved: bool | None = Field(...)
    methane_involved: bool | None = Field(...)
    companion_seam_involved: bool | None = Field(...)
    goaf_accumulation: bool | None = Field(...)
    coal_dust_involved: bool | None = Field(...)
    spontaneous_combustion_involved: bool | None = Field(...)

    # --- Ignition ---
    ignition_source_identified: bool | None = Field(...)
    ignition_type: IgnitionType = Field(
        ..., description="Category of ignition source"
    )

    # --- Technical failure flags ---
    ventilation_failure: bool | None = Field(...)
    degasification_failure: bool | None = Field(...)
    outburst_hazard: bool | None = Field(...)
    geological_hazard: bool | None = Field(...)
    seismic_event: bool | None = Field(...)
    roof_failure: bool | None = Field(...)
    monitoring_failure: bool | None = Field(...)

    # --- Organizational failure flags ---
    data_falsification: bool | None = Field(...)
    naryad_violation: bool | None = Field(...)
    insufficient_supervision: bool | None = Field(...)
    qualification_failure: bool | None = Field(...)

    # --- Severity ---
    fatalities: int = Field(..., ge=0)
    mass_casualty: bool = Field(
        ..., description="True if fatalities >= 5 (mass casualty threshold)"
    )


# ---------------------------------------------------------------------------
# Precedent
# ---------------------------------------------------------------------------

class Precedent(BaseModel):
    """
    A historical accident case record from the precedent knowledge base.

    Sources: Rostechnadzor annual reports (2020-2024), MSHA reports (planned).
    Used by v3 for CBR matching and by agents for contextual reasoning.
    """

    id: str = Field(
        ...,
        pattern=r"^PREC-\d{4}-(GRP-)?\d{2}$",
        description="Precedent ID: PREC-YYYY-NN or PREC-YYYY-GRP-NN",
    )
    year: int = Field(..., ge=1900, le=2100)
    date: str = Field(
        ...,
        min_length=4,
        description="ISO date (YYYY-MM-DD) or just year (YYYY) if exact date unknown",
    )
    record_type: Literal["avaria", "grupovoy_neschastny_sluchay"] = Field(
        default="avaria",
        description="Rostechnadzor classification of the record",
    )
    mine: str = Field(..., min_length=1)
    operator: str = Field(..., min_length=1)
    region: str = Field(..., min_length=1)
    accident_type: str = Field(
        ...,
        min_length=1,
        description="AccidentType label (e.g. 'methane_explosion')",
    )
    work_type: str = Field(
        ...,
        min_length=1,
        description="e.g. 'underground_extraction', 'open_pit'",
    )
    description: str = Field(..., min_length=1)
    fatalities: int = Field(..., ge=0)
    injured: int | None = Field(default=None, ge=0)

    # --- Cause details ---
    technical_causes: list[str] = Field(default_factory=list)
    organizational_causes: list[str] = Field(default_factory=list)
    violated_regulations: list[str] = Field(
        default_factory=list,
        description="REG-XX IDs. Referential integrity checked by KB loader.",
    )
    cause_categories: list[str] = Field(
        default_factory=list,
        description="TC-XX / OC-XX IDs tagged to this case",
    )

    # --- Data quality ---
    data_completeness: DataCompleteness = Field(default=DataCompleteness.FULL)
    completeness_note: str | None = Field(default=None)

    # --- Edge-case fields ---
    generalized_causes_2022: list[str] | None = Field(
        default=None,
        description="Only present for 2022 cases where specific details were not published",
    )

    # --- The matching engine ---
    similarity_profile: SimilarityProfile

    @field_validator("cause_categories")
    @classmethod
    def _validate_cause_ids(cls, v: list[str]) -> list[str]:
        import re
        pattern = re.compile(r"^(TC|OC)-\d{2}$")
        bad = [cid for cid in v if not pattern.match(cid)]
        if bad:
            raise ValueError(f"Invalid cause category IDs: {bad}")
        return v

    @field_validator("violated_regulations")
    @classmethod
    def _validate_reg_ids(cls, v: list[str]) -> list[str]:
        import re
        pattern = re.compile(r"^REG-\d{2}$")
        bad = [rid for rid in v if not pattern.match(rid)]
        if bad:
            raise ValueError(f"Invalid regulation IDs: {bad}")
        return v