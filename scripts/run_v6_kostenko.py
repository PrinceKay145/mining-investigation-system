#!/usr/bin/env python
"""
Run the FULL pipeline (v1 -> v2 -> v3 -> v4 -> v5 -> v6) on Kostenko.

Produces in `runs/<run_id>/`:
  - All intermediate stage artifacts (v1_case.json, v2_classification.json,
    v3_match_result.json, v4_result.json, v5_result.json)
  - argumentation_graph.png — the AF visualization
  - v6_report.json          — structured V6Report
  - report.md               — human-readable markdown report
  - report.html             — single-file HTML report
  - events.jsonl            — full pipeline event log

Expects ANTHROPIC_API_KEY or OPENAI_API_KEY in .env (per LLM_PROVIDER).

Usage:
    python scripts/run_v6_kostenko.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import DEFAULT_KOSTENKO_KB, DEFAULT_REGULATORY_KB, LLM_PROVIDER
from kb.store import KnowledgeBase
from llm import RunContext, make_llm_client
from v1_decomposition import decompose_from_json
from v2_identification import classify
from v3_precedent_matching import match_precedents
from v4_agents import run_v4
from v5_argumentation import run_v5
from v6_report import run_v6


def section(title: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n  {title}\n{bar}")


def main() -> None:
    section("Kostenko full pipeline (v1 -> v2 -> v3 -> v4 -> v5 -> v6)")
    print(f"  LLM provider: {LLM_PROVIDER}")

    run = RunContext(name="kostenko_v6")
    print(f"  Run dir:      {run.dir}")

    # --- KB ---
    kb = KnowledgeBase.from_files(
        regulatory_path=DEFAULT_REGULATORY_KB,
        case_path=DEFAULT_KOSTENKO_KB,
        case_name="kostenko",
    )

    # --- v1 -> v3 (deterministic) ---
    section("Deterministic stages")
    case = decompose_from_json(DEFAULT_KOSTENKO_KB)
    classif = classify(case.arguments, kb.regulations)
    match = match_precedents(classif, kb.precedents)
    print(f"  v1: {len(case.arguments)} expert arguments")
    print(f"  v2: primary={classif.primary_type}, secondary={classif.secondary_types}")
    print(f"  v3: top={match.matches[0].precedent_id if match.matches else 'none'}")

    run.save_artifact("v1_case", case)
    run.save_artifact("v2_classification", classif)
    run.save_artifact("v3_match_result", match)

    # --- v4 (LLM: 4 agents) ---
    section("v4 — 4 specialist agents")
    client = make_llm_client(run_context=run)
    print(f"  Model: {client.model}")
    v4_result = run_v4(
        case=case, classification=classif, match_result=match,
        kb=kb, client=client, run=run,
    )
    print(f"  Agent argument counts: "
          f"A1={len(v4_result.agent_1_arguments)}, "
          f"A2={len(v4_result.agent_2_arguments)}, "
          f"A3={len(v4_result.agent_3_arguments)}, "
          f"A4={len(v4_result.agent_4_arguments)}")

    # --- v5 (LLM: pairwise conflict confirmation) ---
    section("v5 — Argumentation framework")
    combined = case.arguments + v4_result.combined_arguments
    v5_result = run_v5(arguments=combined, client=client, run=run)
    print(f"  Attacks:  {len(v5_result.attack_relations)}")
    print(f"  Supports: {len(v5_result.support_relations)}")
    print(f"  Accepted: {len(v5_result.accepted)}  "
          f"Ambiguous: {len(v5_result.ambiguous)}  "
          f"Rejected: {len(v5_result.rejected)}")

    # --- v6 (LLM: narrative report) ---
    section("v6 — Investigation report")
    report = run_v6(
        case=case, classification=classif, match_result=match,
        v4_result=v4_result, v5_result=v5_result,
        kb=kb, client=client, run=run,
    )
    print(f"  Sections generated: 6 (1-5 + 7)")
    print(f"  Graph rendered:     {run.dir / 'argumentation_graph.png'}")
    print(f"  Markdown report:    {run.dir / 'report.md'}")
    print(f"  HTML report:        {run.dir / 'report.html'}")

    section("Done")
    print(f"  Open the HTML report in a browser:")
    print(f"    open {run.dir / 'report.html'}")


if __name__ == "__main__":
    main()
