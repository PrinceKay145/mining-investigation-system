#!/usr/bin/env python
"""
Run the full v1 -> v2 -> v3 -> v4 -> v5 pipeline against Kostenko.

This is a real API run — expects ANTHROPIC_API_KEY or OPENAI_API_KEY in .env
according to LLM_PROVIDER. Cost: ~$0.30-0.50 per run on gpt-4o
(v4 ~$0.12 + v5 ~$0.20).

Outputs go to runs/<run_id>/ with:
  - v1_case.json, v2_classification.json, v3_match_result.json
  - agent_{1,2,3,4}_raw_response.txt and agent_{1,2,3,4}_arguments.json
  - v4_result.json — combined agent argument set
  - v5_result.json — argumentation framework + extensions
  - events.jsonl — every LLM call + pipeline event

Usage:
    python scripts/run_v5_kostenko.py
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
from llm import RunContext, make_llm_client
from v1_decomposition import decompose_from_json
from v2_identification import classify
from v3_precedent_matching import match_precedents
from v4_agents import run_v4
from v5_argumentation import run_v5


def section(title: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n  {title}\n{bar}")


def main() -> None:
    section("Kostenko end-to-end run (v1 -> v2 -> v3 -> v4 -> v5)")
    print(f"  LLM provider: {LLM_PROVIDER}")

    run = RunContext(name="kostenko_full")
    print(f"  Run dir:      {run.dir}")

    # --- KB ---
    kb = KnowledgeBase.from_files(
        regulatory_path=DEFAULT_REGULATORY_KB,
        case_path=DEFAULT_KOSTENKO_KB,
        case_name="kostenko",
    )

    # --- v1 -> v3 (deterministic, no API calls) ---
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

    run.save_artifact("v1_case", case)
    run.save_artifact("v2_classification", classif)
    run.save_artifact("v3_match_result", match)

    # --- v4 (LLM: 4 agents) ---
    section("v4 — 4 specialist agents")
    client = make_llm_client(run_context=run)
    print(f"  Model: {client.model}")
    print(f"  Phase 1: agents 1, 2, 4 in parallel; Phase 2: agent 3 sequentially.")

    v4_result = run_v4(
        case=case,
        classification=classif,
        match_result=match,
        kb=kb,
        client=client,
        run=run,
    )
    print(f"\n  Agent 1 (Technical):      {len(v4_result.agent_1_arguments):2d} arguments")
    print(f"  Agent 2 (Organizational): {len(v4_result.agent_2_arguments):2d} arguments")
    print(f"  Agent 3 (Challenger):     {len(v4_result.agent_3_arguments):2d} arguments")
    print(f"  Agent 4 (Regulatory):     {len(v4_result.agent_4_arguments):2d} arguments")

    combined = case.arguments + v4_result.combined_arguments
    print(
        f"\n  Combined for v5: {len(combined)} arguments "
        f"({len(case.arguments)} expert + {len(v4_result.combined_arguments)} agent)"
    )

    # --- v5 (LLM: pairwise conflict confirmation) ---
    section("v5 — Argumentation framework")
    print("  Topic filter → LLM confirmation → AF construction → semantics.")
    v5_result = run_v5(arguments=combined, client=client, run=run)

    print(f"\n  Attacks detected:           {len(v5_result.attack_relations):3d}")
    print(f"  Supports detected:          {len(v5_result.support_relations):3d}")
    print(f"  Preferred extensions:       {len(v5_result.preferred_extensions):3d}")
    print(f"  Consensus (grounded = preferred): {v5_result.grounded_equals_preferred}")
    print()
    print(f"  Accepted (grounded):  {len(v5_result.accepted):3d} arguments")
    print(f"  Rejected:             {len(v5_result.rejected):3d} arguments")
    print(f"  Ambiguous:            {len(v5_result.ambiguous):3d} arguments")

    # --- Sample attacks ---
    if v5_result.attack_relations:
        section("v5 — Sample attacks (first 5)")
        for atk in v5_result.attack_relations[:5]:
            print(f"\n  [{atk.id}] {atk.attacker} -> {atk.target} ({atk.type.value})")
            print(f"      {atk.description[:160]}")

    # --- Sample supports ---
    if v5_result.support_relations:
        section("v5 — Sample supports (first 3)")
        for sup in v5_result.support_relations[:3]:
            print(f"\n  [{sup.id}] {' + '.join(sup.supporters)} ({sup.topic})")
            print(f"      {sup.description[:160]}")

    # --- Acceptance preview ---
    section("v5 — Acceptance preview (first 8 of each)")
    print("\n  Accepted (the system's confident conclusions):")
    for arg_id in v5_result.accepted[:8]:
        print(f"    - {arg_id}")
    if len(v5_result.accepted) > 8:
        print(f"    ... and {len(v5_result.accepted) - 8} more")

    if v5_result.ambiguous:
        print("\n  Ambiguous (defensible but contested):")
        for arg_id in v5_result.ambiguous[:8]:
            print(f"    - {arg_id}")
        if len(v5_result.ambiguous) > 8:
            print(f"    ... and {len(v5_result.ambiguous) - 8} more")

    if v5_result.rejected:
        print("\n  Rejected (defeated by other arguments):")
        for arg_id in v5_result.rejected[:8]:
            print(f"    - {arg_id}")
        if len(v5_result.rejected) > 8:
            print(f"    ... and {len(v5_result.rejected) - 8} more")

    section("Done")
    print(f"  Artifacts in: {run.dir}")
    print(f"  Inspect:      cat {run.dir}/v5_result.json | head -50")


if __name__ == "__main__":
    main()
