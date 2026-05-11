"""
V5Result — output of the v5 argumentation stage, consumed by v6.

Holds the detected attack and support relations, the computed grounded
and preferred extensions, the derived acceptance status of every argument,
and the full NetworkX DiGraph serialized as node-link JSON (for v6
visualization).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from schema.ground_truth import AttackRelation, SupportRelation


class V5Result(BaseModel):
    """Output of the v5 argumentation framework over the combined argument set."""

    attack_relations: list[AttackRelation] = Field(
        default_factory=list,
        description="Detected attacks (rebutting + undercutting).",
    )
    support_relations: list[SupportRelation] = Field(
        default_factory=list,
        description="Detected pairwise supports (LLM-confirmed agreement on same topic).",
    )

    grounded_extension: list[str] = Field(
        default_factory=list,
        description="Argument IDs in the grounded extension. Skeptical conclusions.",
    )
    preferred_extensions: list[list[str]] = Field(
        default_factory=list,
        description="List of preferred extensions, each as a list of argument IDs. "
                    "Multiple extensions indicate defensible alternative worldviews.",
    )

    accepted: list[str] = Field(
        default_factory=list,
        description="Argument IDs the system accepts = grounded_extension.",
    )
    rejected: list[str] = Field(
        default_factory=list,
        description="Argument IDs in no preferred extension. Defeated hypotheses.",
    )
    ambiguous: list[str] = Field(
        default_factory=list,
        description="Argument IDs in some preferred extension but not all. Genuinely contested.",
    )

    af_graph: dict = Field(
        default_factory=dict,
        description="NetworkX DiGraph as node-link JSON. v6 renders this.",
    )

    @property
    def grounded_equals_preferred(self) -> bool:
        """
        True iff the grounded extension equals every preferred extension.
        This is the 'consensus' case — no genuine ambiguity in the evidence.
        """
        if not self.preferred_extensions:
            return not self.grounded_extension
        g = set(self.grounded_extension)
        return all(set(p) == g for p in self.preferred_extensions)
