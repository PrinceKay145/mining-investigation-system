#!/usr/bin/env python
"""
Evaluate a v5 run against the manually-annotated ground truth in the
Kostenko case file.

Reports:
  - Attack detection coverage (TP / FP / FN against the 4 GT attacks)
  - Support detection coverage (the 5 GT support clusters → pairwise expansion)
  - Acceptance distribution (accepted / rejected / ambiguous, by source)
  - Open-question coverage (do v5's ambiguous args correspond to the 5 GT open questions?)

Usage:
    # Most recent kostenko_full_* run (default)
    python scripts/evaluate_kostenko.py

    # Specific run
    python scripts/evaluate_kostenko.py --run-dir runs/kostenko_full_<timestamp>

Produces structured output suitable for the thesis evaluation section.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import RUNS_DIR  # noqa: E402


def section(title: str) -> None:
    bar = "=" * 75
    print(f"\n{bar}\n  {title}\n{bar}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_most_recent_run() -> Path:
    """
    Locate the most recent Kostenko run that has a v5_result.json.

    Matches any directory under `runs/` whose name starts with `kostenko_`
    — covers both the legacy `kostenko_full_*` naming and the current
    `kostenko_v6_*` produced by `scripts/run_v6_kostenko.py`. Excludes
    private dirs like `_pair_cache/`.
    """
    if not RUNS_DIR.is_dir():
        raise FileNotFoundError(f"No runs directory at {RUNS_DIR}")
    candidates = sorted(
        (
            p for p in RUNS_DIR.iterdir()
            if p.is_dir()
            and p.name.startswith("kostenko_")
            and (p / "v5_result.json").is_file()
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"No kostenko_* run with v5_result.json in {RUNS_DIR}"
        )
    return candidates[0]


def load_run(run_dir: Path) -> tuple[dict, dict, dict | None]:
    """Return (v5_result, v1_case, v4_result or None)."""
    with open(run_dir / "v5_result.json") as f:
        v5 = json.load(f)
    with open(run_dir / "v1_case.json") as f:
        case = json.load(f)
    v4_path = run_dir / "v4_result.json"
    v4 = json.loads(v4_path.read_text()) if v4_path.is_file() else None
    return v5, case, v4


# ---------------------------------------------------------------------------
# Attack-coverage analysis
# ---------------------------------------------------------------------------

def classify_attack_match(gt: dict, v5_attacks: list[dict]) -> tuple[str, dict | None]:
    """
    Classify how v5 matched a ground-truth attack.

    Returns (status, matched_attack):
      EXACT         — same pair, same direction, same type
      TYPE_MISMATCH — same pair (same direction), different type
      DIRECTION_FLIPPED — same pair (opposite direction), same type
      BOTH_MISMATCH — same pair (any direction), neither match
      MISSED        — neither pair direction found anywhere in v5
    """
    a, t, ty = gt["attacker"], gt["target"], gt["type"]
    # Look for forward and reverse direction matches
    forward = next((x for x in v5_attacks if x["attacker"] == a and x["target"] == t), None)
    reverse = next((x for x in v5_attacks if x["attacker"] == t and x["target"] == a), None)

    if forward and forward["type"] == ty:
        return ("EXACT", forward)
    if reverse and reverse["type"] == ty:
        return ("DIRECTION_FLIPPED", reverse)
    if forward:
        return ("TYPE_MISMATCH", forward)
    if reverse:
        return ("BOTH_MISMATCH", reverse)
    return ("MISSED", None)


def attack_coverage_report(v5: dict, case: dict) -> dict:
    gt_attacks = case["ground_truth"]["attack_relations"]
    v5_attacks = v5["attack_relations"]

    rows = []
    for gt in gt_attacks:
        status, matched = classify_attack_match(gt, v5_attacks)
        rows.append({"gt": gt, "status": status, "matched": matched})

    detected = sum(1 for r in rows if r["status"] != "MISSED")
    exact = sum(1 for r in rows if r["status"] == "EXACT")
    return {
        "rows": rows,
        "gt_count": len(gt_attacks),
        "v5_count": len(v5_attacks),
        "detected": detected,
        "exact": exact,
        "novel": len(v5_attacks)
                 - sum(1 for r in rows if r["status"] != "MISSED" and r["matched"] is not None),
    }


def print_attack_coverage(rep: dict) -> None:
    section("Attack coverage vs ground truth")
    print(f"  Ground-truth attacks:  {rep['gt_count']}")
    print(f"  v5 attacks:            {rep['v5_count']}")
    print(f"  GT detected (any form): {rep['detected']} / {rep['gt_count']}")
    print(f"  GT detected exactly:   {rep['exact']} / {rep['gt_count']}")
    print(f"  Novel attacks (not in GT): ~{rep['novel']}")
    print()
    for r in rep["rows"]:
        gt = r["gt"]
        m = r["matched"]
        print(f"  {gt['id']}: {gt['attacker']} -> {gt['target']} ({gt['type']})  [{r['status']}]")
        if m is not None:
            print(f"    v5: {m['attacker']} -> {m['target']} ({m['type']})  ({m['id']})")


# ---------------------------------------------------------------------------
# Support-coverage analysis
# ---------------------------------------------------------------------------

def support_coverage_report(v5: dict, case: dict) -> dict:
    """
    For each GT support cluster (multiple members), expand to all pairwise
    pairs and check whether each pair appears in v5's pairwise support
    relations.
    """
    gt_supports = case["ground_truth"]["support_relations"]
    v5_support_pairs = {
        frozenset(s["supporters"]) for s in v5["support_relations"]
        if len(s["supporters"]) == 2
    }

    rows = []
    for gt in gt_supports:
        members = gt["supporters"]
        expected_pairs = list(combinations(members, 2))
        hits = [p for p in expected_pairs if frozenset(p) in v5_support_pairs]
        rows.append({
            "gt": gt,
            "expected_pairs": expected_pairs,
            "hit_pairs": hits,
            "coverage": len(hits) / len(expected_pairs) if expected_pairs else 0.0,
        })

    total_expected = sum(len(r["expected_pairs"]) for r in rows)
    total_hit = sum(len(r["hit_pairs"]) for r in rows)
    return {
        "rows": rows,
        "v5_support_count": len(v5["support_relations"]),
        "gt_support_clusters": len(gt_supports),
        "total_pairs_expected": total_expected,
        "total_pairs_hit": total_hit,
    }


def print_support_coverage(rep: dict) -> None:
    section("Support coverage vs ground truth (pairwise expansion)")
    print(f"  Ground-truth support clusters:    {rep['gt_support_clusters']}")
    print(f"  v5 pairwise supports:             {rep['v5_support_count']}")
    print(f"  Expected pairwise supports (from GT clusters): {rep['total_pairs_expected']}")
    print(f"  Detected:                         {rep['total_pairs_hit']} / {rep['total_pairs_expected']}")
    print()
    for r in rep["rows"]:
        gt = r["gt"]
        print(f"  {gt['id']} ({gt['topic']}) — strength={gt['strength']}, members={gt['supporters']}")
        print(f"    Expected pairs: {r['expected_pairs']}")
        print(f"    Detected:       {r['hit_pairs']}  ({len(r['hit_pairs'])}/{len(r['expected_pairs'])})")


# ---------------------------------------------------------------------------
# Acceptance distribution
# ---------------------------------------------------------------------------

def acceptance_distribution(v5: dict, case: dict, v4: dict | None) -> dict:
    accepted = set(v5["accepted"])
    rejected = set(v5["rejected"])
    ambiguous = set(v5["ambiguous"])

    def categorize(arg_id: str) -> str:
        if arg_id in accepted: return "accepted"
        if arg_id in rejected: return "rejected"
        if arg_id in ambiguous: return "ambiguous"
        return "unclassified"

    expert_ids = [a["id"] for a in case["arguments"]]
    agent_ids = []
    if v4 is not None:
        for k in ("agent_1_arguments", "agent_2_arguments",
                  "agent_3_arguments", "agent_4_arguments"):
            agent_ids.extend(a["id"] for a in v4.get(k, []))

    expert_dist = Counter(categorize(i) for i in expert_ids)
    agent_dist = Counter(categorize(i) for i in agent_ids)
    return {
        "expert_dist": expert_dist,
        "agent_dist": agent_dist,
        "expert_total": len(expert_ids),
        "agent_total": len(agent_ids),
    }


def print_acceptance_distribution(rep: dict) -> None:
    section("Acceptance distribution")
    print(f"  By source:")
    print(f"               accepted   ambiguous   rejected   total")
    for label, dist, total in [
        ("Expert (v1)", rep["expert_dist"], rep["expert_total"]),
        ("Agent  (v4)", rep["agent_dist"], rep["agent_total"]),
    ]:
        print(f"    {label}    "
              f"{dist['accepted']:>6}    {dist['ambiguous']:>8}    "
              f"{dist['rejected']:>7}    {total:>6}")


# ---------------------------------------------------------------------------
# Open-question coverage
# ---------------------------------------------------------------------------

# Hand-mapping from GT open question → argument IDs that genuinely address it.
# Source: Kostenko KB ground-truth open_questions + manual reading of arg claims.
_OPEN_QUESTION_RELATED_ARGS = {
    "OQ-1": ["D-A5"],                          # was shearer operating?
    "OQ-2": ["U-A3", "U-A1", "D-A5", "D-A6"],  # angle grinder at ignition location?
    "OQ-3": ["K-A7", "D-A8"],                  # CH4 distribution before explosion
    "OQ-4": ["D-A9", "K-A8"],                  # coal dust explosivity
    "OQ-5": ["K-A8", "D-A9", "K-A7", "D-A7"],  # explosion propagation
}


def open_question_coverage(v5: dict, case: dict) -> dict:
    accepted = set(v5["accepted"])
    rejected = set(v5["rejected"])
    ambiguous = set(v5["ambiguous"])
    gt_oqs = case["ground_truth"]["open_questions"]

    rows = []
    for oq in gt_oqs:
        related = _OPEN_QUESTION_RELATED_ARGS.get(oq["id"], [])
        # An open question is "captured" if v5 has at least one related arg
        # in ambiguous (= contested but defensible)
        ambig_hits = [a for a in related if a in ambiguous]
        rejected_hits = [a for a in related if a in rejected]
        accepted_hits = [a for a in related if a in accepted]
        rows.append({
            "oq": oq,
            "related_args": related,
            "in_ambiguous": ambig_hits,
            "in_rejected": rejected_hits,
            "in_accepted": accepted_hits,
            "captured": bool(ambig_hits),
        })

    captured = sum(1 for r in rows if r["captured"])
    return {"rows": rows, "captured": captured, "total": len(gt_oqs)}


def print_open_question_coverage(rep: dict) -> None:
    section("Open-question coverage")
    print(f"  GT open questions:  {rep['total']}")
    print(f"  Captured as ambiguous in v5:  {rep['captured']} / {rep['total']}")
    print()
    print("  An open question is 'captured' if at least one related argument")
    print("  appears in v5's ambiguous set (contested but defensible).")
    print()
    for r in rep["rows"]:
        oq = r["oq"]
        status = "CAPTURED" if r["captured"] else "NOT CAPTURED"
        print(f"  {oq['id']} [{status}] — {oq['question'][:80]}")
        print(f"    Related args:  {r['related_args']}")
        print(f"    In ambiguous:  {r['in_ambiguous']}")
        print(f"    In rejected:   {r['in_rejected']}")
        print(f"    In accepted:   {r['in_accepted']}")


# ---------------------------------------------------------------------------
# Axis 6 — Per-expert agreement (Jaccard with Usembekov / Kolikov / DMT)
# ---------------------------------------------------------------------------

# Expert-source ID prefixes for the three Kostenko commission reports.
# See note.md "Kostenko knowledge base" section for the full per-expert
# argument inventory.
_EXPERT_PREFIXES: dict[str, str] = {
    "U-": "Usembekov",
    "K-": "Kolikov",
    "D-": "DMT",
}


def _expert_from_id(arg_id: str) -> str | None:
    """Return the expert source name for an argument ID, or None if it's an agent ID."""
    for prefix, name in _EXPERT_PREFIXES.items():
        if arg_id.startswith(prefix):
            return name
    return None


def per_expert_agreement(v5: dict, case: dict) -> dict:
    """
    Compute Jaccard agreement between v5's accepted set and each expert source.

    Three stats per expert:
      - `jaccard` = |X ∩ A| / |X ∪ A| (symmetric agreement, the headline metric)
      - `coverage_of_expert` = |X ∩ A| / |X| (what fraction of this expert's
        args did v5 accept? — asymmetric, easier to interpret)
      - per-bucket counts (accepted / ambiguous / rejected for this expert's args)

    The Jaccard *spread* (max - min across the three experts) tells the
    thesis story: large spread = v5 aligns with one expert (bias); small
    spread = v5 synthesizes across experts (the strong story).
    """
    accepted = set(v5["accepted"])
    ambiguous = set(v5["ambiguous"])
    rejected = set(v5["rejected"])

    expert_args: dict[str, set[str]] = {name: set() for name in _EXPERT_PREFIXES.values()}
    for arg in case["arguments"]:
        expert = _expert_from_id(arg["id"])
        if expert is not None:
            expert_args[expert].add(arg["id"])

    rows = []
    for expert, expert_set in expert_args.items():
        intersection = expert_set & accepted
        union = expert_set | accepted
        jaccard = len(intersection) / len(union) if union else 0.0
        coverage = len(intersection) / len(expert_set) if expert_set else 0.0
        rows.append({
            "expert": expert,
            "expert_arg_count": len(expert_set),
            "accepted_count": len(intersection),
            "ambiguous_count": len(expert_set & ambiguous),
            "rejected_count": len(expert_set & rejected),
            "jaccard": jaccard,
            "coverage_of_expert": coverage,
        })

    jaccards = [r["jaccard"] for r in rows if r["expert_arg_count"] > 0]
    spread = max(jaccards) - min(jaccards) if jaccards else 0.0
    return {
        "rows": rows,
        "spread": spread,
        "interpretation": _interpret_spread(spread, rows),
    }


def _interpret_spread(spread: float, rows: list[dict]) -> str:
    """Map per-expert Jaccard spread to one of three thesis-defensible stories."""
    if not rows or all(r["expert_arg_count"] == 0 for r in rows):
        return "NO_EXPERTS — no expert-sourced arguments in this case file"
    if spread >= 0.15:
        max_row = max(rows, key=lambda r: r["jaccard"])
        return (
            f"BIASED — v5 aligns most strongly with {max_row['expert']} "
            f"(Jaccard={max_row['jaccard']:.2f}); spread={spread:.2f}"
        )
    if spread <= 0.05:
        return (
            "BALANCED — v5 synthesizes across experts "
            f"(Jaccard differences within {spread:.2f})"
        )
    return f"MIXED — partial synthesis with some bias (spread={spread:.2f})"


def print_per_expert_agreement(rep: dict) -> None:
    section("Per-expert agreement (Axis 6)")
    print()
    print(
        f"  {'Expert':<12}  {'Args':>4}  {'Accept':>6}  {'Ambig':>6}  "
        f"{'Reject':>6}  {'Coverage':>9}  {'Jaccard':>8}"
    )
    print(
        f"  {'-'*12}  {'-'*4}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*9}  {'-'*8}"
    )
    for r in rep["rows"]:
        if r["expert_arg_count"] == 0:
            continue
        print(
            f"  {r['expert']:<12}  {r['expert_arg_count']:>4}  "
            f"{r['accepted_count']:>6}  {r['ambiguous_count']:>6}  "
            f"{r['rejected_count']:>6}  "
            f"{r['coverage_of_expert']*100:>8.1f}%  {r['jaccard']:>8.3f}"
        )
    print()
    print(f"  Jaccard spread (max - min):  {rep['spread']:.3f}")
    print(f"  Story:                       {rep['interpretation']}")
    print()
    print("  Coverage = |expert ∩ accepted| / |expert|")
    print("  Jaccard  = |expert ∩ accepted| / |expert ∪ accepted|")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Path to a runs/kostenko_full_*/ directory. "
             "Defaults to the most recent one with a v5_result.json.",
    )
    args = parser.parse_args()

    run_dir = args.run_dir or find_most_recent_run()
    section("Evaluating v5 run against Kostenko ground truth")
    print(f"  Run: {run_dir.name}")

    v5, case, v4 = load_run(run_dir)
    print(f"  Combined argument count: "
          f"{len(case['arguments']) + sum(len(v4.get(k, [])) for k in (
              'agent_1_arguments', 'agent_2_arguments',
              'agent_3_arguments', 'agent_4_arguments',
          )) if v4 else len(case['arguments'])}")

    attack_rep = attack_coverage_report(v5, case)
    print_attack_coverage(attack_rep)

    support_rep = support_coverage_report(v5, case)
    print_support_coverage(support_rep)

    acc_rep = acceptance_distribution(v5, case, v4)
    print_acceptance_distribution(acc_rep)

    oq_rep = open_question_coverage(v5, case)
    print_open_question_coverage(oq_rep)

    pea_rep = per_expert_agreement(v5, case)
    print_per_expert_agreement(pea_rep)

    # --- Final summary ---
    section("Summary")
    print(f"  Attack coverage:       {attack_rep['detected']}/{attack_rep['gt_count']} "
          f"detected ({attack_rep['exact']} exact)")
    print(f"  Support coverage:      {support_rep['total_pairs_hit']}/"
          f"{support_rep['total_pairs_expected']} expected pairs detected")
    print(f"  Open-question capture: {oq_rep['captured']}/{oq_rep['total']} captured "
          f"as ambiguous")
    print(f"  Per-expert Jaccard:    " + ", ".join(
        f"{r['expert']}={r['jaccard']:.2f}" for r in pea_rep["rows"]
        if r["expert_arg_count"] > 0
    ))
    print(f"  ({pea_rep['interpretation']})")
    print(f"  Acceptance:            "
          f"{acc_rep['expert_dist']['accepted'] + acc_rep['agent_dist']['accepted']} accepted, "
          f"{acc_rep['expert_dist']['ambiguous'] + acc_rep['agent_dist']['ambiguous']} ambiguous, "
          f"{acc_rep['expert_dist']['rejected'] + acc_rep['agent_dist']['rejected']} rejected")


if __name__ == "__main__":
    main()
