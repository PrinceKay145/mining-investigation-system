"""
V4Result — output of the v4 multi-agent stage, consumed by v5.

Holds the parsed arguments from each agent separately (for traceability and
per-agent inspection in the v6 report) and exposes a `combined_arguments`
view that v5 consumes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from schema.argument import Argument


class V4Result(BaseModel):
    """The four agents' outputs from one v4 invocation."""

    agent_1_arguments: list[Argument] = Field(
        default_factory=list,
        description="Technical Causes Analyst output",
    )
    agent_2_arguments: list[Argument] = Field(
        default_factory=list,
        description="Organizational and Human Factors Analyst output",
    )
    agent_3_arguments: list[Argument] = Field(
        default_factory=list,
        description="Independent Challenger output (runs after 1, 2, 4)",
    )
    agent_4_arguments: list[Argument] = Field(
        default_factory=list,
        description="Regulatory Compliance Checker output",
    )

    @property
    def combined_arguments(self) -> list[Argument]:
        """All four agents' outputs concatenated — the input set for v5."""
        return [
            *self.agent_1_arguments,
            *self.agent_2_arguments,
            *self.agent_3_arguments,
            *self.agent_4_arguments,
        ]
