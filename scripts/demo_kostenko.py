#!/usr/bin/env python
"""
Kostenko end-to-end demonstration.

Runs the full v1 → v2 → v3 deterministic pipeline against the Kostenko
mine explosion (Kazakhstan, 2023) and prints what each subsystem produces.

Designed for live demonstration of the working scaffold before the
LLM-backed v4–v6 layers are wired in.

Usage:
    python scripts/demo_kostenko.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

# Make src/ importable regardless of how the script is invoked
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import DEFAULT_REGULATORY_KB, DEFAULT_KOSTENKO_KB
from kb.store import KnowledgeBase
from v1_decomposition import decompose_from_json
from v2_identification import classify
from v3_precedent_matching import match_precedents


def section(title: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n  {title}\n{bar}")


def main() -> None:
    section("Mining Accident Investigation System — Kostenko Demonstration")
    print("  Test case: Kostenko mine explosion, Kazakhstan, 2023-10-28")
    print("  Pipeline:  v1 (load) -> v2 (classify) -> v3 (CBR)")

    # --- Knowledge base ---
    section("Knowledge base")
    kb = KnowledgeBase.from_files(
        regulatory_path=DEFAULT_REGULATORY_KB,
        case_path=DEFAULT_KOSTENKO_KB,
        case_name="kostenko",
    )
    for k, v in kb.summary().items():
        print(f"  {k:>20}: {v}")

    # --- v1: decomposition ---
    section("v1 — Decomposition (Mode 1: structured JSON)")
    case = decompose_from_json(DEFAULT_KOSTENKO_KB)
    print(f"  Loaded {len(case.arguments)} arguments from "
          f"{len(case.metadata.sources)} expert sources")

    by_source = Counter(a.source for a in case.arguments)
    for src, count in sorted(by_source.items()):
        src_meta = next(
            (s for s in case.metadata.sources if s.get("id") == src), {}
        )
        full_name = src_meta.get("full_name", "?")
        affiliation = src_meta.get("affiliation", "")
        print(f"    {src}: {count:2d} args  -- {full_name} ({affiliation})")

    sample = case.arguments[0]
    print(f"\n  Sample argument [{sample.id}] (topic: {sample.topic}):")
    print(f"    claim:            {sample.claim}")
    print(f"    confidence:       {sample.confidence}")
    print(f"    cause_categories: {sample.cause_categories}")

    print(f"\n  Ground truth (held aside for v5 evaluation):")
    gt = case.ground_truth
    print(f"    {len(gt.attack_relations):2d} attack relations")
    print(f"    {len(gt.support_relations):2d} support relations")
    print(f"    {len(gt.open_questions):2d} open questions")

    # --- v2: identification ---
    section("v2 — Identification (rule-based classification)")
    classif = classify(case.arguments, kb.regulations)
    print(f"  Primary type:    {classif.primary_type}")
    print(f"  Secondary types: {classif.secondary_types}")

    print(f"\n  Cause profile (frequency across {len(case.arguments)} arguments):")
    for cid, count in sorted(classif.cause_profile.items(),
                             key=lambda x: (-x[1], x[0])):
        cat = kb.get_cause_category(cid)
        label = cat.label if cat else "?"
        bar = "#" * count
        print(f"    {cid}  {label:<32}  {bar} ({count})")

    print(f"\n  Type votes (full ranking):")
    for type_label, votes in sorted(classif.type_votes.items(),
                                    key=lambda x: (-x[1], x[0])):
        bar = "#" * max(votes // 2, 1)
        print(f"    {type_label:<25}  {bar} ({votes})")

    # --- v3: precedent matching ---
    section("v3 — Precedent matching (two-step CBR)")
    match_result = match_precedents(classif, kb.precedents)
    print(f"  Funnel: {match_result.total_precedents} precedents in KB "
          f"-> {match_result.filtered_count} passed type filter")

    print(f"\n  Ranked matches (Jaccard overlap on cause_categories):")
    if not match_result.matches:
        print("    (none)")
    else:
        for i, m in enumerate(match_result.matches, 1):
            prec = next(p for p in kb.precedents if p.id == m.precedent_id)
            print(f"    {i}. {m.precedent_id} — {prec.mine}")
            print(f"       accident_type:   {m.accident_type} "
                  f"(matched_via: {m.matched_via})")
            print(f"       overlap_score:   {m.overlap_score:.4f}")
            print(f"       shared causes:   {m.shared_cause_categories}")
            print(f"       fatalities:      {prec.fatalities}")

    # --- Summary ---
    section("What this demonstrates")
    print("  Built and verified end-to-end:")
    print("    - 4 Pydantic schema modules (data contracts)")
    print("    - Knowledge base loader + store with referential integrity")
    print("    - v1: structured JSON -> validated CaseFile")
    print("    - v2: rule-based accident-type classification")
    print("    - v3: two-step CBR (type filter + Jaccard)")
    print()
    print("  Test coverage: 90 unit + integration tests")
    print("  Run:  pytest")
    print()
    print("  Pending (thesis contribution):")
    print("    - v4: 4 specialist LLM agents")
    print("           (Technical, Organizational, Challenger, Regulatory)")
    print("    - v5: Dung's argumentation framework (NetworkX)")
    print("    - v6: LLM-generated explainable report")


if __name__ == "__main__":
    main()
