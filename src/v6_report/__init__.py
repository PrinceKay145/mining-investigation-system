"""
v6 Report Generation — final stage of the pipeline.

Takes the structured outputs of v1..v5 and produces a human-readable
investigation report. One LLM call generates the seven narrative
sections (Pydantic-validated); the AF graph is rendered separately
as a PNG; markdown and HTML versions of the assembled report are
saved alongside the run artifacts.

Outputs in `runs/<run_id>/`:
  - v6_report.json         — V6Report (the structured object)
  - report.md              — assembled markdown
  - report.html            — single-file HTML
  - argumentation_graph.png — the AF visualization
"""

from __future__ import annotations

from pathlib import Path

from kb.store import KnowledgeBase
from llm import LLMClient
from llm.logging import RunContext
from prompts import load_prompt
from schema.classification import ClassificationResult
from schema.ground_truth import CaseFile
from schema.precedent_match import PrecedentMatchResult
from schema.v4_result import V4Result
from schema.v5_result import V5Result
from schema.v6_report import V6Report, V6ReportContent
from v6_report.context import build_context
from v6_report.renderer import render_html, render_markdown
from v6_report.visualizer import render_af_graph

__all__ = ["run_v6", "V6Report"]


def run_v6(
    *,
    case: CaseFile,
    classification: ClassificationResult,
    match_result: PrecedentMatchResult,
    v4_result: V4Result,
    v5_result: V5Result,
    kb: KnowledgeBase,
    client: LLMClient,
    run: RunContext,
    temperature: float = 0.3,
) -> V6Report:
    """
    Generate the final investigation report.

    Args:
        case, classification, match_result, v4_result, v5_result: pipeline
            outputs from earlier stages.
        kb: KnowledgeBase (for cause taxonomy + regulations lookups).
        client: LLMClient. The narrative call uses `temperature=0.3` for
                light creative freedom — investigation prose, not data.
        run: RunContext for telemetry + artifact persistence.
        temperature: LLM temperature for the narrative generation step.

    Returns:
        V6Report (also written to runs/<run_id>/v6_report.json).
        Markdown and HTML versions written to report.md / report.html.
        AF graph rendered as argumentation_graph.png.
    """
    run.event("v6_start", run_id=run.run_id)

    # --- 1. AF graph (deterministic, no LLM) ---
    graph_path = render_af_graph(
        v5_result,
        run.dir / "argumentation_graph.png",
        title=f"Argumentation framework — {case.metadata.case}",
    )
    run.event("v6_graph_rendered", path=str(graph_path))

    # --- 2. Build context for the LLM ---
    context = build_context(
        case=case,
        classification=classification,
        match_result=match_result,
        v4_result=v4_result,
        v5_result=v5_result,
        cause_categories=kb.cause_categories,
        precedents=kb.precedents,
        regulations=kb.regulations,
    )
    run.event("v6_context_built", context_chars=sum(len(v) for v in context.values()))

    # --- 3. Narrative generation (one LLM call) ---
    prompt = load_prompt("v6_report", **context)
    content = client.complete_json(
        prompt=prompt,
        schema=V6ReportContent,
        temperature=temperature,
    )
    run.event(
        "v6_narrative_done",
        sections=[
            "incident_summary",
            "classification_and_precedents",
            "accepted_conclusions",
            "rejected_hypotheses",
            "unresolved_questions",
            "regulatory_violations",
        ],
        total_chars=sum(len(getattr(content, k)) for k in (
            "incident_summary", "classification_and_precedents",
            "accepted_conclusions", "rejected_hypotheses",
            "unresolved_questions", "regulatory_violations",
        )),
    )

    # --- 4. Assemble V6Report ---
    combined_count = len(case.arguments) + len(v4_result.combined_arguments)
    report = V6Report(
        content=content,
        case_name=case.metadata.case,
        case_date=case.metadata.date,
        run_id=run.run_id,
        # Use a relative path in the markdown so the report renders correctly
        # from inside the run dir
        graph_path=graph_path.name,
        counts={
            "combined_arguments": combined_count,
            "expert_arguments": len(case.arguments),
            "agent_arguments": len(v4_result.combined_arguments),
            "attacks_detected": len(v5_result.attack_relations),
            "supports_detected": len(v5_result.support_relations),
            "accepted": len(v5_result.accepted),
            "ambiguous": len(v5_result.ambiguous),
            "rejected": len(v5_result.rejected),
            "preferred_extensions": len(v5_result.preferred_extensions),
        },
    )

    # --- 5. Persist (structured + markdown + HTML) ---
    run.save_artifact("v6_report", report)
    md_path = run.dir / "report.md"
    md_path.write_text(render_markdown(report), encoding="utf-8")
    html_path = run.dir / "report.html"
    html_path.write_text(render_html(report), encoding="utf-8")

    run.event(
        "v6_done",
        v6_report=str(run.dir / "v6_report.json"),
        markdown=str(md_path),
        html=str(html_path),
        graph=str(graph_path),
    )
    return report
