"""
Ground truth and case file models.

Three relation models (the manual annotations v5 is evaluated against):
  AttackRelation   — one argument attacks another
  SupportRelation  — multiple arguments converge on the same conclusion
  OpenQuestion     — unresolved questions identified by experts

One container:
  GroundTruth      — bundles attacks + supports + open questions
  CaseFile         — bundles .arguments (pipeline input) + .ground_truth (eval target)

Design notes:
  - CaseFile is the top-level object for a single investigation case.
    It holds both the data the pipeline processes (arguments) and the
    data we evaluate against (ground truth). One object, clear boundary.
  - Argument IDs in attack/support relations are validated as non-empty
    strings. Referential integrity (do these IDs actually exist in the
    argument list?) is checked at the KB loader level, not here.
  - AttackType distinguishes rebutting (mutual) from undercutting (directed).
    This maps directly to Dung's AF edge semantics in v5.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from schema.argument import Argument


# ---------------------------------------------------------------------------
# Attack relations
# ---------------------------------------------------------------------------

class AttackType(str, Enum):
    """
    Dung's AF attack classification.

    REBUTTING:    claims reach contradictory conclusions (mutual attack).
                  In the AF graph, this generates edges in both directions.
    UNDERCUTTING:  one claim undermines the evidence/warrant of another
                  (directed attack — only attacker → target).
    """
    REBUTTING = "rebutting"
    UNDERCUTTING = "undercutting"


class AttackRelation(BaseModel):
    """
    An attack relation between two arguments.

    Examples:
        ATK-1: U-A3 attacks D-A5 (rebutting) — specific vs unknown ignition source
        ATK-4: K-A7 attacks D-A8 (undercutting) — divergent explosion locations
    """
    id: str = Field(
        ...,
        pattern=r"^ATK-\d+$",
        description="Attack relation ID: ATK-N",
    )
    attacker: str = Field(
        ...,
        min_length=1,
        description="ID of the attacking argument",
    )
    target: str = Field(
        ...,
        min_length=1,
        description="ID of the attacked argument",
    )
    type: AttackType = Field(
        ...,
        description="Rebutting (mutual) or undercutting (directed)",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable explanation of why this attack holds",
    )


# ---------------------------------------------------------------------------
# Support relations
# ---------------------------------------------------------------------------

class SupportStrength(str, Enum):
    """How many sources agree."""
    UNANIMOUS = "unanimous"    # all experts converge
    BILATERAL = "bilateral"   # two of three experts converge


class SupportRelation(BaseModel):
    """
    A support relation — multiple arguments converging on the same conclusion.

    Not edges in Dung's AF (which only has attacks), but tracked separately
    for evaluation and report generation. Support clusters are strong
    candidates for the grounded extension.

    Examples:
        SUP-1: U-A2 + K-A3 + D-A4 all exclude spontaneous combustion (unanimous)
        SUP-4: K-A2 + D-A1 both identify K2 seam as methane source (bilateral)
    """
    id: str = Field(
        ...,
        pattern=r"^SUP-\d+$",
        description="Support relation ID: SUP-N",
    )
    supporters: list[str] = Field(
        ...,
        min_length=2,
        description="IDs of the arguments that mutually support each other",
    )
    topic: str = Field(
        ...,
        min_length=1,
        description="The shared conclusion these arguments converge on",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Why these arguments support each other",
    )
    strength: SupportStrength = Field(
        ...,
        description="Unanimous (all experts) or bilateral (two of three)",
    )


# ---------------------------------------------------------------------------
# Open questions
# ---------------------------------------------------------------------------

class OpenQuestion(BaseModel):
    """
    An unresolved question identified during investigation.

    These map to v5's "ambiguous" set — arguments that appear in some
    preferred extensions but not all.

    Examples:
        OQ-1: Was the shearer operating at the time of ignition?
        OQ-4: Were coal dust samples from conveyor lines explosive?
    """
    id: str = Field(
        ...,
        pattern=r"^OQ-\d+$",
        description="Open question ID: OQ-N",
    )
    question: str = Field(
        ...,
        min_length=1,
        description="The unresolved question",
    )
    relevance: str = Field(
        ...,
        min_length=1,
        description="Why resolving this question matters for the investigation",
    )
    raised_by: list[str] = Field(
        ...,
        min_length=1,
        description="Source IDs of experts who raised this question",
    )


# ---------------------------------------------------------------------------
# GroundTruth — evaluation target bundle
# ---------------------------------------------------------------------------

class GroundTruth(BaseModel):
    """
    The manually annotated argumentation framework for a case.

    This is what v5's output is evaluated against: does the system
    discover the same attacks, supports, and ambiguities that human
    experts identified?
    """
    attack_relations: list[AttackRelation] = Field(default_factory=list)
    support_relations: list[SupportRelation] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# CaseFile — the top-level container
# ---------------------------------------------------------------------------

class CaseMetadata(BaseModel):
    """Metadata about the investigation case."""
    case: str = Field(..., min_length=1)
    date: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    investigation_questions: list[str] = Field(default_factory=list)
    extra: dict[str, Any] | None = Field(
        default=None,
        description="Any additional metadata (e.g. longwall ID)",
    )


class CaseFile(BaseModel):
    """
    Top-level container for a single investigation case.

    Bundles two things:
      .arguments    — the structured evidence (pipeline input for v1→v4)
      .ground_truth — the manually annotated AF (evaluation target for v5)

    One object, clear boundary. The pipeline processes .arguments;
    evaluation compares v5 output against .ground_truth.
    """
    metadata: CaseMetadata
    arguments: list[Argument]
    ground_truth: GroundTruth