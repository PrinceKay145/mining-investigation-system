#!/usr/bin/env python
"""
Run the full v1 -> v2 -> v3 -> v4 pipeline against Kostenko, using whichever
LLM provider is configured in .env (LLM_PROVIDER = "anthropic" or "openai").

This is a real API run — expects ANTHROPIC_API_KEY or OPENAI_API_KEY in .env.
Cost: a few cents per run on gpt-4o or claude-opus-4-7.

Outputs go to runs/<run_id>/ with:
  - events.jsonl             — every pipeline event with timing/token counts
  - agent_{1,2,3,4}_raw_response.txt
  - agent_{1,2,3,4}_arguments.json
  - v4_result.json           — combined agent argument set (v5 input)

Usage:
    python scripts/run_v4_kostenko.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make src/ importable regardless of how the script is invoked
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import DEFAULT_KOSTENKO_KB, DEFAULT_REGULATORY_KB, LLM_PROVIDER
from kb.store import KnowledgeBase
from llm import RunContext
from v1_decomposition import decompose_from_json
from v2_identification import classify
from v3_precedent_matching import match_precedents
from v4_agents import build_v4_agent_clients, run_v4


def section(title: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n  {title}\n{bar}")


def main() -> None:
    section("Kostenko end-to-end run (v1 -> v2 -> v3 -> v4)")
    print(f"  LLM provider: {LLM_PROVIDER}")

    run = RunContext(name="kostenko_v4")
    print(f"  Run dir:      {run.dir}")

    # --- KB ---
    kb = KnowledgeBase.from_files(
        regulatory_path=DEFAULT_REGULATORY_KB,
        case_path=DEFAULT_KOSTENKO_KB,
        case_name="kostenko",
    )

    # --- v1 → v2 → v3 (deterministic, no API calls) ---
    section("Deterministic stages")
    case = decompose_from_json(DEFAULT_KOSTENKO_KB)
    print(f"  v1: loaded {len(case.arguments)} expert arguments")

    classif = classify(case.arguments, kb.regulations)
    print(f"  v2: primary={classif.primary_type}, secondary={classif.secondary_types}")

    match = match_precedents(classif, kb.precedents)
    print(f"  v3: {match.filtered_count} of {match.total_precedents} precedents passed type filter")
    for m in match.matches:
        prec = next(p for p in kb.precedents if p.id == m.precedent_id)
        print(f"      - {m.precedent_id} ({prec.mine}) overlap={m.overlap_score:.3f}")

    # Persist intermediate stages so v5 can re-read them
    run.save_artifact("v1_case", case)
    run.save_artifact("v2_classification", classif)
    run.save_artifact("v3_match_result", match)

    # --- v4 (the LLM stage) ---
    section("v4 — calling 4 specialist agents")
    clients = build_v4_agent_clients(run_context=run)
    print("  Per-agent models:")
    for agent_id in ("agent_1", "agent_2", "agent_3", "agent_4"):
        print(f"    {agent_id}: {clients[agent_id].model}")
    print("  Phase 1: agents 1, 2, 4 in parallel ...")

    result = run_v4(
        case=case,
        classification=classif,
        match_result=match,
        kb=kb,
        clients=clients,
        run=run,
    )

    # --- Summary ---
    section("v4 results")
    print(f"  Agent 1 (Technical):      {len(result.agent_1_arguments):2d} arguments")
    print(f"  Agent 2 (Organizational): {len(result.agent_2_arguments):2d} arguments")
    print(f"  Agent 3 (Challenger):     {len(result.agent_3_arguments):2d} arguments")
    print(f"  Agent 4 (Regulatory):     {len(result.agent_4_arguments):2d} arguments")
    total_for_v5 = len(result.combined_arguments) + len(case.arguments)
    print(f"  Combined for v5:          {len(result.combined_arguments):2d} agent arguments")
    print(f"  (+ {len(case.arguments)} expert arguments from v1 = {total_for_v5} total)")

    section("Spot check — one argument per agent")
    for agent_args, label in [
        (result.agent_1_arguments, "Agent 1 — Technical"),
        (result.agent_2_arguments, "Agent 2 — Organizational"),
        (result.agent_3_arguments, "Agent 3 — Challenger"),
        (result.agent_4_arguments, "Agent 4 — Regulatory"),
    ]:
        if not agent_args:
            print(f"\n  {label}: (no arguments produced)")
            continue
        a = agent_args[0]
        print(f"\n  {label}")
        print(f"    id:               {a.id}")
        print(f"    topic:            {a.topic}")
        print(f"    claim:            {a.claim}")
        print(f"    cause_categories: {a.cause_categories}")
        print(f"    confidence:       {a.confidence}")

    section("Done")
    print(f"  Artifacts in: {run.dir}")
    print(f"  Inspect:      cat {run.dir}/events.jsonl")


if __name__ == "__main__":
    main()
