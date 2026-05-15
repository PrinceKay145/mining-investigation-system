"""
Schemas for LLM-as-judge structured output (Axes 5 and 7).

Axis 7 — v6 report quality
    `V6ReportJudgeResult` is the structured output of the v6 report judge
    prompt. Five rubric dimensions × {score, rationale} + overall comments +
    a list of flagged issues. The judge is deterministic (temperature=0) and
    runs against the user's direct OpenAI key so judge spend is isolated
    from the OpenRouter pipeline budget.

Why a fixed rubric over free-form scoring:
    Reproducibility. The thesis evaluation chapter must be able to re-run
    the judge against the same v6 report and get the same numbers ±
    sampling noise. A fixed 5-dimension rubric with explicit anchors at
    score 1, 3, and 5 makes the judge's task well-specified, the output
    machine-readable, and the comparison across runs (Axes 2, 3, 4) a
    straightforward 5-tuple diff.
"""

from __future__ import annotations

import statistics

from pydantic import BaseModel, Field


# Score range for every rubric dimension.
# Floats (not ints) so the judge can give partial credit (e.g. 3.5).
MIN_SCORE = 1.0
MAX_SCORE = 5.0


class RubricScore(BaseModel):
    """Single rubric dimension: numeric score + the judge's justification."""

    score: float = Field(
        ge=MIN_SCORE,
        le=MAX_SCORE,
        description="Score on the 1.0-5.0 scale defined for this rubric dimension.",
    )
    rationale: str = Field(
        min_length=10,
        description="2-4 sentence justification anchored in specific report content.",
    )


class V6ReportJudgeResult(BaseModel):
    """
    Structured output of the v6 report LLM-as-judge (Axis 7).

    Dimensions are graded against the rubric defined in
    `prompts/judge_v6_report.md`; see that file for the score-anchor text
    (what score 1 vs 3 vs 5 means for each dimension).
    """

    factual_accuracy: RubricScore = Field(
        description="Does every factual claim in the report align with the GT case file?"
    )
    completeness: RubricScore = Field(
        description="Does the report address each of the 5 GT open questions?"
    )
    citation_correctness: RubricScore = Field(
        description="Does every [ARG-ID] / [ATK-V5-*] citation resolve to a real artifact?"
    )
    narrative_coherence: RubricScore = Field(
        description="Does the report read as a coherent investigation narrative, "
                    "not as a list of independent paragraphs?"
    )
    defense_readiness: RubricScore = Field(
        description="Could this report be filed as-is in a formal investigation, "
                    "or would it require substantive editing first?"
    )
    overall_comments: str = Field(
        min_length=20,
        description="High-level synthesis: what the report does well, "
                    "what its weakest dimension is, and whether the weakness is "
                    "structural (model/pipeline limit) or surface (copy-edit fix).",
    )
    flagged_issues: list[str] = Field(
        default_factory=list,
        description="Specific items a human editor should fix before filing: "
                    "broken citations, hallucinated regulations, factual errors, "
                    "open questions left unaddressed. Empty list means no blockers.",
    )

    @property
    def overall_score(self) -> float:
        """Mean of the five rubric dimensions. Computed, not judged."""
        return statistics.mean([
            self.factual_accuracy.score,
            self.completeness.score,
            self.citation_correctness.score,
            self.narrative_coherence.score,
            self.defense_readiness.score,
        ])


# ---------------------------------------------------------------------------
# Axis 5 — Argument-quality (per-argument rubric)
# ---------------------------------------------------------------------------

class ArgumentQualityScores(BaseModel):
    """
    Four-dimension rubric scores for ONE v4-generated argument (Axis 5).

    Per-dimension definitions (full anchors are in `prompts/judge_argument_quality.md`):
      - **evidence_groundedness** — does the argument's evidence field
        reference real evidence from the case file (not invented)?
      - **warrant_validity** — does the reasoning step from evidence
        to claim actually hold? (a strong evidence statement with a
        non-sequitur warrant gets a low score here)
      - **claim_novelty** — does this argument add something not already
        covered by an expert argument or another agent's argument? A
        paraphrase of an existing argument scores low here.
      - **citation_correctness** — every cited `cause_category` and
        `regulation_id` field in the argument resolves to a real KB
        entry. Hallucinated TC-/OC-/REG- codes fail this dimension hard.
    """

    arg_id: str = Field(description="The argument's ID (e.g. 'agent_1_001').")
    evidence_groundedness: RubricScore
    warrant_validity: RubricScore
    claim_novelty: RubricScore
    citation_correctness: RubricScore
    comments: str = Field(
        min_length=10,
        description="One-sentence overall comment specific to this argument.",
    )

    @property
    def mean_score(self) -> float:
        """Mean of the four rubric dimensions for this argument."""
        return statistics.mean([
            self.evidence_groundedness.score,
            self.warrant_validity.score,
            self.claim_novelty.score,
            self.citation_correctness.score,
        ])


class ArgumentQualityResult(BaseModel):
    """
    Structured output of the argument-quality judge for an entire v4 run.

    The judge produces a flat list of per-argument scores (`scores`) plus a
    single high-level synthesis (`overall_comments`). The evaluator script
    then computes per-agent aggregate means and per-dimension distributions
    — done in Python (not by the judge) for deterministic arithmetic.
    """

    scores: list[ArgumentQualityScores] = Field(
        description="Per-argument scores, one entry per v4-generated argument."
    )
    overall_comments: str = Field(
        min_length=20,
        description="High-level synthesis across all v4 agents. Should call out "
                    "which agent produced the strongest / weakest arguments and "
                    "on which rubric dimension(s).",
    )
