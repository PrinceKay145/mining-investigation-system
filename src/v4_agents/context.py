"""
Context formatting helpers for the v4 agent prompts.

Each agent prompt expects several variables in the Jinja2 template
(investigation_questions, accident_classification, precedent_matches,
evidence_arguments, cause_taxonomy, canonical_topics, and — Agent 4 only —
regulatory_requirements). These helpers turn the upstream data structures
(case file, ClassificationResult, PrecedentMatchResult, KB) into the
formatted strings (or lists) the templates render.

All functions here are pure: no I/O, no side effects.
"""

from __future__ import annotations

import json

from schema.argument import Argument
from schema.classification import ClassificationResult
from schema.precedent import Precedent
from schema.precedent_match import PrecedentMatchResult
from schema.taxonomy import CauseCategory, Regulation


# ---------------------------------------------------------------------------
# Investigation questions
# ---------------------------------------------------------------------------

def format_investigation_questions(questions: list[str]) -> str:
    """Bullet-list the investigation questions for the prompt context."""
    if not questions:
        return "(no investigation questions provided)"
    return "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))


# ---------------------------------------------------------------------------
# Accident classification (v2 output)
# ---------------------------------------------------------------------------

def format_classification(
    result: ClassificationResult,
    cause_categories: dict[str, CauseCategory] | None = None,
) -> str:
    """
    Render the v2 classification as a human-readable block.

    If `cause_categories` is provided, includes the taxonomy label for each
    cause in the profile (e.g. 'TC-01 methane_accumulation: 7').
    """
    lines = [
        f"Primary accident type:    {result.primary_type}",
        f"Secondary accident types: {', '.join(result.secondary_types) or '(none)'}",
        "",
        "Cause profile (frequency across all evidence arguments):",
    ]
    for cid, count in sorted(result.cause_profile.items(), key=lambda x: (-x[1], x[0])):
        if cause_categories and cid in cause_categories:
            label = cause_categories[cid].label
            lines.append(f"  {cid} {label}: {count}")
        else:
            lines.append(f"  {cid}: {count}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Precedent matches (v3 output)
# ---------------------------------------------------------------------------

def format_precedent_matches(
    result: PrecedentMatchResult,
    precedents: list[Precedent],
) -> str:
    """
    Render the ranked precedent matches with enough detail for an agent to
    cite them. Looks up each match in the supplied precedents list for the
    descriptive fields (mine, fatalities, accident description).
    """
    if not result.matches:
        return (
            f"Funnel: {result.total_precedents} precedents considered, "
            f"{result.filtered_count} passed type filter, none matched."
        )

    by_id = {p.id: p for p in precedents}
    lines = [
        f"Funnel: {result.total_precedents} precedents considered, "
        f"{result.filtered_count} passed type filter ({len(result.matches)} after threshold).",
        "",
        "Ranked matches:",
    ]
    for i, m in enumerate(result.matches, 1):
        p = by_id.get(m.precedent_id)
        lines.append(f"")
        lines.append(f"{i}. {m.precedent_id} — {p.mine if p else 'unknown mine'}")
        lines.append(f"   accident_type:   {m.accident_type} (matched_via: {m.matched_via})")
        lines.append(f"   overlap_score:   {m.overlap_score:.4f}")
        lines.append(f"   shared causes:   {', '.join(m.shared_cause_categories) or '(none)'}")
        if p:
            lines.append(f"   fatalities:      {p.fatalities}")
            lines.append(f"   description:     {p.description}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Evidence arguments (v1 output → agent input)
# ---------------------------------------------------------------------------

def format_evidence_arguments(arguments: list[Argument]) -> str:
    """
    Render the case arguments as a JSON array — preserves structure so the
    agent can cite specific IDs and fields verbatim in its outputs.
    """
    return json.dumps(
        [a.model_dump() for a in arguments],
        indent=2,
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Cause taxonomy
# ---------------------------------------------------------------------------

def format_cause_taxonomy(cause_categories: dict[str, CauseCategory]) -> str:
    """Render the cause taxonomy grouped by tier, with descriptions."""
    technical = sorted(
        (c for c in cause_categories.values() if c.id.startswith("TC-")),
        key=lambda c: c.id,
    )
    organizational = sorted(
        (c for c in cause_categories.values() if c.id.startswith("OC-")),
        key=lambda c: c.id,
    )

    lines = ["## Technical causes (TC-*)", ""]
    for c in technical:
        lines.append(f"- **{c.id}** `{c.label}` — {c.description}")
    lines.append("")
    lines.append("## Organizational causes (OC-*)")
    lines.append("")
    for c in organizational:
        lines.append(f"- **{c.id}** `{c.label}` — {c.description}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Regulatory requirements (Agent 4 only)
# ---------------------------------------------------------------------------

def format_regulatory_requirements(regulations: dict[str, Regulation]) -> str:
    """Render all regulations as a numbered list for Agent 4's prompt."""
    sorted_regs = sorted(regulations.values(), key=lambda r: r.id)
    lines = []
    for r in sorted_regs:
        lines.append(f"### {r.id} — {r.topic}")
        lines.append("")
        lines.append(f"**Requirement:** {r.requirement}")
        lines.append("")
        lines.append(f"**Standard:** {r.applicable_standard}")
        if r.applies_to_accident_types:
            lines.append(
                f"**Applies to:** {', '.join(r.applies_to_accident_types)}"
            )
        if r.relevant_cause_categories:
            lines.append(
                f"**Cause categories:** {', '.join(r.relevant_cause_categories)}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Canonical topics (extracted from case arguments at runtime)
# ---------------------------------------------------------------------------

def extract_canonical_topics(arguments: list[Argument]) -> list[str]:
    """
    Return the unique topic labels used by the case arguments, sorted
    alphabetically. The result is the `canonical_topics` template variable
    that Agents 1, 2, 4 receive — the vocabulary they should reuse when
    addressing the same investigation questions.
    """
    return sorted({a.topic for a in arguments})


# ---------------------------------------------------------------------------
# Agent output serialization (for Agent 3's context)
# ---------------------------------------------------------------------------

def format_agent_arguments(arguments: list[Argument]) -> str:
    """
    Render a list of agent-produced arguments as a JSON array — used to
    inject Agents 1/2/4 outputs into Agent 3's prompt.
    """
    return json.dumps(
        [a.model_dump() for a in arguments],
        indent=2,
        ensure_ascii=False,
    )
