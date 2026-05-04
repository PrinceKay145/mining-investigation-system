"""
ClassificationResult — output of v2 identification, consumed by v3 and v6.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClassificationResult(BaseModel):
    """v2's structured output: dominant accident type plus supporting evidence."""

    primary_type: str = Field(
        ...,
        description="Most likely accident type label, e.g. 'methane_explosion'. "
                    "'unknown' if no arguments produce votes.",
    )
    secondary_types: list[str] = Field(
        default_factory=list,
        description="Other types whose vote count meets the secondary threshold.",
    )
    cause_profile: dict[str, int] = Field(
        default_factory=dict,
        description="Frequency of each cause_category across all arguments.",
    )
    type_votes: dict[str, int] = Field(
        default_factory=dict,
        description="Raw votes per accident type — for transparency / debugging.",
    )

    @property
    def all_cause_categories(self) -> set[str]:
        """Set of cause categories present in the arguments — for v3 Jaccard."""
        return set(self.cause_profile.keys())
