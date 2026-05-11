"""
Context formatters for the v6 report prompt.

Take the pipeline outputs (v1 case, v2 classification, v3 matches, v4 result,
v5 result) and the KB, and produce formatted strings the v6 prompt template
renders into the LLM input. Pure functions, no I/O.
"""

from __future__ import annotations

from collections import defaultdict

from schema.argument import Argument
from schema.classification import ClassificationResult
from schema.ground_truth import CaseFile
from schema.precedent import Precedent
from schema.precedent_match import PrecedentMatchResult
from schema.taxonomy import CauseCategory, Regulation
from schema.v4_result import V4Result
from schema.v5_result import V5Result


def format_investigation_questions(questions: list[str]) -> str:
    if not questions:
        return "(none recorded)"
    return "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))


def format_expert_sources(sources: list[dict]) -> str:
    if not sources:
        return "(no source metadata available)"
    lines = []
    for s in sources:
        lines.append(
            f"- **{s.get('id', '?')}** — {s.get('full_name', '?')} "
            f"({s.get('affiliation', '?')}, {s.get('role', '?')})"
        )
    return "\n".join(lines)


def format_classification_summary(
    c: ClassificationResult,
    cause_categories: dict[str, CauseCategory],
) -> str:
    lines = [
        f"- **Primary type:** {c.primary_type}",
        f"- **Secondary types:** {', '.join(c.secondary_types) or '(none)'}",
        f"- **Cause profile (frequency across arguments):**",
    ]
    for cid, n in sorted(c.cause_profile.items(), key=lambda x: (-x[1], x[0])):
        label = cause_categories[cid].label if cid in cause_categories else cid
        lines.append(f"  - {cid} `{label}`: {n}")
    return "\n".join(lines)


def format_precedent_summary(
    match: PrecedentMatchResult,
    precedents: list[Precedent],
) -> str:
    by_id = {p.id: p for p in precedents}
    lines = [
        f"- Funnel: {match.total_precedents} precedents in KB → "
        f"{match.filtered_count} passed type filter → "
        f"{len(match.matches)} after threshold.",
        "",
        "Ranked matches:",
    ]
    for i, m in enumerate(match.matches, 1):
        p = by_id.get(m.precedent_id)
        mine = p.mine if p else "?"
        fatalities = p.fatalities if p else 0
        lines.append(
            f"{i}. **{m.precedent_id}** — {mine}  "
            f"(accident_type: {m.accident_type}, matched_via: {m.matched_via}, "
            f"overlap: {m.overlap_score:.4f}, shared: {m.shared_cause_categories}, "
            f"fatalities: {fatalities})"
        )
        if p:
            lines.append(f"   - {p.description[:200]}")
    return "\n".join(lines)


def format_all_arguments_summary(arguments: list[Argument]) -> str:
    """
    One line per argument: ID, source, topic, claim.
    Grouped by source for readability.
    """
    by_source: dict[str, list[Argument]] = defaultdict(list)
    for a in arguments:
        by_source[a.source].append(a)

    lines: list[str] = []
    for source in sorted(by_source.keys()):
        lines.append(f"### Source: `{source}` ({len(by_source[source])} arguments)")
        lines.append("")
        for a in by_source[source]:
            lines.append(
                f"- **{a.id}** [{a.topic}] (conf={a.confidence}, "
                f"categories={a.cause_categories})"
            )
            lines.append(f"  - claim: {a.claim}")
            lines.append(f"  - evidence: {a.evidence[:180]}")
        lines.append("")
    return "\n".join(lines)


def format_attacks_summary(v5: V5Result) -> str:
    if not v5.attack_relations:
        return "(no attacks detected)"
    lines = [f"Total: {len(v5.attack_relations)} attacks detected."]
    for atk in v5.attack_relations:
        lines.append(
            f"- **{atk.id}**: `{atk.attacker}` → `{atk.target}` "
            f"({atk.type.value})  — {atk.description[:160]}"
        )
    return "\n".join(lines)


def format_supports_summary(v5: V5Result) -> str:
    if not v5.support_relations:
        return "(no supports detected)"
    lines = [f"Total: {len(v5.support_relations)} supports detected."]
    for sup in v5.support_relations:
        lines.append(
            f"- **{sup.id}** [{sup.topic}] supporters={sup.supporters} "
            f"({sup.strength.value})  — {sup.description[:160]}"
        )
    return "\n".join(lines)


def _arg_lookup(arguments: list[Argument]) -> dict[str, Argument]:
    return {a.id: a for a in arguments}


def _format_arg_list(arg_ids: list[str], arg_lookup: dict[str, Argument]) -> str:
    if not arg_ids:
        return "(none)"
    lines = []
    for arg_id in arg_ids:
        a = arg_lookup.get(arg_id)
        if a is None:
            lines.append(f"- `{arg_id}` (argument not found in combined set)")
            continue
        lines.append(f"- **{arg_id}** [{a.topic}] ({a.source})  — {a.claim[:200]}")
    return "\n".join(lines)


def format_accepted_summary(v5: V5Result, arguments: list[Argument]) -> str:
    return _format_arg_list(v5.accepted, _arg_lookup(arguments))


def format_ambiguous_summary(v5: V5Result, arguments: list[Argument]) -> str:
    return _format_arg_list(v5.ambiguous, _arg_lookup(arguments))


def format_rejected_summary(v5: V5Result, arguments: list[Argument]) -> str:
    return _format_arg_list(v5.rejected, _arg_lookup(arguments))


def format_open_questions(case: CaseFile) -> str:
    qs = case.ground_truth.open_questions
    if not qs:
        return "(none)"
    lines = []
    for oq in qs:
        lines.append(f"- **{oq.id}**: {oq.question}")
        if oq.relevance:
            lines.append(f"  - relevance: {oq.relevance}")
        if oq.raised_by:
            lines.append(f"  - raised by: {', '.join(oq.raised_by)}")
    return "\n".join(lines)


def format_regulations_summary(regulations: dict[str, Regulation]) -> str:
    lines = []
    for reg in sorted(regulations.values(), key=lambda r: r.id):
        lines.append(f"- **{reg.id}** — {reg.topic}")
        lines.append(f"  - requirement: {reg.requirement[:240]}")
    return "\n".join(lines)


def build_context(
    case: CaseFile,
    classification: ClassificationResult,
    match_result: PrecedentMatchResult,
    v4_result: V4Result,
    v5_result: V5Result,
    cause_categories: dict[str, CauseCategory],
    precedents: list[Precedent],
    regulations: dict[str, Regulation],
) -> dict[str, str]:
    """
    Bundle all the formatted strings the v6 prompt template needs.
    Returned dict keys correspond 1-1 to the {{ var }} placeholders in
    prompts/v6_report.md.
    """
    combined = list(case.arguments) + list(v4_result.combined_arguments)

    extra = case.metadata.extra or {}
    return {
        "case_name": case.metadata.case,
        "case_date": case.metadata.date,
        "case_location": case.metadata.location,
        "investigation_questions": format_investigation_questions(
            case.metadata.investigation_questions
        ),
        "expert_sources": format_expert_sources(case.metadata.sources),
        "classification_summary": format_classification_summary(
            classification, cause_categories
        ),
        "precedent_summary": format_precedent_summary(match_result, precedents),
        "all_arguments_summary": format_all_arguments_summary(combined),
        "attacks_summary": format_attacks_summary(v5_result),
        "supports_summary": format_supports_summary(v5_result),
        "accepted_summary": format_accepted_summary(v5_result, combined),
        "ambiguous_summary": format_ambiguous_summary(v5_result, combined),
        "rejected_summary": format_rejected_summary(v5_result, combined),
        "open_questions": format_open_questions(case),
        "regulations_summary": format_regulations_summary(regulations),
    }
