#!/usr/bin/env python
"""
Axis 8 — Failure-mode auto-classifier for a single canonical Kostenko run.

For every ground-truth attack and support pair that v5 did not detect
exactly, walks the pipeline stage-by-stage and classifies *which* stage
dropped it, into one of four buckets (per note.md Axis 8 spec):

  1. **Generation miss** — v4 / v1 never produced one of the two arguments.
  2. **Detection miss** — argument existed but the topic-string filter
     excluded the pair from the LLM confirmation candidate set.
  3. **Confirmation miss** — the pair reached the LLM but was scored
     as `support` / `independent` rather than an attack relation.
  4. **Semantics demotion** — the LLM confirmed the attack, but it didn't
     appear in v5's final `attack_relations` (or appeared with wrong
     direction / type / so was demoted in semantics).

This is the script that turns "v5 missed ATK-X" into the mechanistic
explanation a thesis defense needs.

Inputs (all from one run dir):
  - v5_result.json       — v5's final attack_relations / support_relations
  - v4_result.json (opt) — v4 agent argument inventory
  - events.jsonl         — all v5_pair_check_done events with relations
  - case file (GT)       — attack_relations + support_relations to compare against

Outputs:
  - axis8_failure_modes.json into the run dir
  - Stdout: structured table per GT attack + per missed support pair

Usage:
    # Most recent run
    python scripts/classify_failure_modes.py

    # Specific run
    python scripts/classify_failure_modes.py --run-dir runs/kostenko_v6_<id>
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import DEFAULT_KOSTENKO_KB, RUNS_DIR  # noqa: E402


def section(title: str) -> None:
    bar = "=" * 75
    print(f"\n{bar}\n  {title}\n{bar}")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict | list:
    return json.loads(path.read_text())


def _load_events(run_dir: Path) -> list[dict]:
    return [
        json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]


def _build_args_by_id(case: dict, v4: dict | None) -> dict[str, dict]:
    """Index every argument (expert + agent) by ID."""
    idx: dict[str, dict] = {a["id"]: a for a in case.get("arguments", [])}
    if v4:
        for k in ("agent_1_arguments", "agent_2_arguments",
                  "agent_3_arguments", "agent_4_arguments"):
            for a in v4.get(k, []):
                idx[a["id"]] = a
    return idx


# ---------------------------------------------------------------------------
# Pipeline-stage lookups
# ---------------------------------------------------------------------------

def _find_pair_check_event(a: str, b: str, events: list[dict]) -> dict | None:
    """
    Return the v5_pair_check_done event for the (a, b) pair in either order.

    Returns None if the pair never reached the LLM confirmation step
    (i.e. it was excluded by the topic filter or otherwise skipped).
    """
    pair_set = {a, b}
    for e in events:
        if e.get("event") != "v5_pair_check_done":
            continue
        if {e.get("arg_a"), e.get("arg_b")} == pair_set:
            return e
    return None


def _find_v5_attack(
    attacker: str, target: str, v5: dict, exact_direction: bool = True,
) -> dict | None:
    """Find a v5 attack relation matching (attacker, target)."""
    for atk in v5.get("attack_relations", []):
        if exact_direction:
            if atk["attacker"] == attacker and atk["target"] == target:
                return atk
        else:
            if {atk["attacker"], atk["target"]} == {attacker, target}:
                return atk
    return None


def _find_v5_support_pair(a: str, b: str, v5: dict) -> dict | None:
    """Find a v5 support cluster containing both a and b."""
    for sup in v5.get("support_relations", []):
        members = set(sup.get("supporters", []))
        if a in members and b in members:
            return sup
    return None


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------

# Four buckets, per note.md Axis 8 spec
STAGE_GENERATION   = "generation_miss"
STAGE_DETECTION    = "detection_miss"
STAGE_CONFIRMATION = "confirmation_miss"
STAGE_SEMANTICS    = "semantics_demotion"
STAGE_DETECTED     = "detected"  # not a miss; included for completeness


def classify_attack(
    gt_attack: dict,
    v5: dict,
    events: list[dict],
    args_by_id: dict[str, dict],
) -> dict:
    """Classify what happened to one GT attack."""
    attacker = gt_attack["attacker"]
    target = gt_attack["target"]
    classification: dict = {
        "gt_id": gt_attack["id"],
        "gt_attacker": attacker,
        "gt_target": target,
        "gt_type": gt_attack["type"],
    }

    # Stage 1: Generation
    if attacker not in args_by_id:
        classification["stage"] = STAGE_GENERATION
        classification["reason"] = f"attacker '{attacker}' not present in v1+v4 argument set"
        return classification
    if target not in args_by_id:
        classification["stage"] = STAGE_GENERATION
        classification["reason"] = f"target '{target}' not present in v1+v4 argument set"
        return classification

    # Stage 2: Detection (topic filter)
    pair_event = _find_pair_check_event(attacker, target, events)
    if pair_event is None:
        a_topic = args_by_id[attacker].get("topic", "?")
        t_topic = args_by_id[target].get("topic", "?")
        classification["stage"] = STAGE_DETECTION
        classification["reason"] = (
            f"topic filter excluded the pair "
            f"(attacker topic='{a_topic}', target topic='{t_topic}')"
        )
        classification["attacker_topic"] = a_topic
        classification["target_topic"] = t_topic
        return classification

    # Stage 3: Confirmation (LLM)
    llm_relation = pair_event.get("relation")
    classification["llm_relation"] = llm_relation
    classification["llm_rationale"] = pair_event.get("rationale", "")[:200]

    if llm_relation in ("support", "independent"):
        classification["stage"] = STAGE_CONFIRMATION
        classification["reason"] = (
            f"LLM classified pair as '{llm_relation}' instead of attack; "
            f"expected '{gt_attack['type']}'"
        )
        return classification

    # Stage 4: Semantics / AF construction
    # Did v5 produce an attack relation for this pair?
    v5_atk = _find_v5_attack(attacker, target, v5, exact_direction=True)
    if v5_atk:
        if v5_atk["type"] == gt_attack["type"]:
            classification["stage"] = STAGE_DETECTED
            classification["form"] = "exact"
            classification["v5_id"] = v5_atk["id"]
            return classification
        classification["stage"] = STAGE_DETECTED
        classification["form"] = "type_mismatch"
        classification["v5_id"] = v5_atk["id"]
        classification["v5_type"] = v5_atk["type"]
        return classification

    # Maybe direction is flipped
    reverse = _find_v5_attack(target, attacker, v5, exact_direction=True)
    if reverse:
        classification["stage"] = STAGE_DETECTED
        classification["form"] = "direction_flipped"
        classification["v5_id"] = reverse["id"]
        classification["v5_attacker"] = reverse["attacker"]
        classification["v5_target"] = reverse["target"]
        classification["v5_type"] = reverse["type"]
        return classification

    # LLM confirmed an attack relation but v5_result has neither direction → demoted by AF
    classification["stage"] = STAGE_SEMANTICS
    classification["reason"] = (
        f"LLM relation was '{llm_relation}' (an attack class) but no matching "
        f"attack appears in v5_result.attack_relations in either direction"
    )
    return classification


def classify_support_pair(
    pair: tuple[str, str],
    sup_cluster: dict,
    v5: dict,
    events: list[dict],
    args_by_id: dict[str, dict],
) -> dict:
    """Classify what happened to one expected support pair from a GT cluster."""
    a, b = pair
    classification: dict = {
        "gt_cluster_id": sup_cluster["id"],
        "gt_cluster_topic": sup_cluster.get("topic", "?"),
        "pair": [a, b],
    }

    # Stage 1: Generation
    if a not in args_by_id or b not in args_by_id:
        missing = [x for x in pair if x not in args_by_id]
        classification["stage"] = STAGE_GENERATION
        classification["reason"] = f"args missing from v1+v4 set: {missing}"
        return classification

    # Stage 2: Detection
    pair_event = _find_pair_check_event(a, b, events)
    if pair_event is None:
        ta = args_by_id[a].get("topic", "?")
        tb = args_by_id[b].get("topic", "?")
        classification["stage"] = STAGE_DETECTION
        classification["reason"] = (
            f"topic filter excluded the pair ('{ta}' vs '{tb}')"
        )
        classification["topics"] = [ta, tb]
        return classification

    # Stage 3: Confirmation
    llm_relation = pair_event.get("relation")
    classification["llm_relation"] = llm_relation
    classification["llm_rationale"] = pair_event.get("rationale", "")[:200]

    if llm_relation != "support":
        classification["stage"] = STAGE_CONFIRMATION
        classification["reason"] = (
            f"LLM classified pair as '{llm_relation}' instead of 'support'"
        )
        return classification

    # Stage 4: Semantics — confirmed as support but not in v5 supports?
    found = _find_v5_support_pair(a, b, v5)
    if found:
        classification["stage"] = STAGE_DETECTED
        classification["form"] = "exact"
        classification["v5_id"] = found["id"]
        return classification

    classification["stage"] = STAGE_SEMANTICS
    classification["reason"] = (
        "LLM confirmed pair as support but no v5 support cluster contains both members"
    )
    return classification


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_STAGE_LABEL = {
    STAGE_GENERATION:   "GENERATION",
    STAGE_DETECTION:    "DETECTION",
    STAGE_CONFIRMATION: "CONFIRMATION",
    STAGE_SEMANTICS:    "SEMANTICS",
    STAGE_DETECTED:     "DETECTED",
}


def print_attack_classifications(rows: list[dict]) -> None:
    section("Attack failure-mode classification")
    print()
    for r in rows:
        stage = _STAGE_LABEL[r["stage"]]
        marker = "MISS" if r["stage"] != STAGE_DETECTED else r.get("form", "exact").upper()
        print(f"  [{r['gt_id']}] {r['gt_attacker']} → {r['gt_target']} ({r['gt_type']})")
        print(f"      stage={stage}  result={marker}")
        if r["stage"] != STAGE_DETECTED:
            print(f"      reason: {r.get('reason', '')}")
        elif r["stage"] == STAGE_DETECTED and r.get("form") != "exact":
            print(f"      v5: {r.get('v5_attacker', r['gt_attacker'])} → "
                  f"{r.get('v5_target', r['gt_target'])} ({r.get('v5_type', '?')})")
        if r.get("llm_rationale"):
            print(f"      llm: {r['llm_rationale'][:120]}")
        print()


def print_support_classifications(rows: list[dict]) -> None:
    section("Support pair failure-mode classification (only missed pairs shown)")
    print()
    missed = [r for r in rows if r["stage"] != STAGE_DETECTED]
    if not missed:
        print("  (no missed support pairs)")
        return
    for r in missed:
        stage = _STAGE_LABEL[r["stage"]]
        print(f"  [{r['gt_cluster_id']}] pair {r['pair']}  (topic: {r['gt_cluster_topic']})")
        print(f"      stage={stage}")
        print(f"      reason: {r.get('reason', '')}")
        if r.get("llm_rationale"):
            print(f"      llm: {r['llm_rationale'][:120]}")
        print()


def print_summary(attack_rows: list[dict], support_rows: list[dict]) -> None:
    section("Axis 8 — Failure-mode taxonomy summary")
    print()
    print("  Bucket            Attacks    Supports")
    print(f"  {'-'*16}  {'-'*9}  {'-'*8}")
    for stage in (STAGE_GENERATION, STAGE_DETECTION, STAGE_CONFIRMATION, STAGE_SEMANTICS):
        atk_n = sum(1 for r in attack_rows if r["stage"] == stage)
        sup_n = sum(1 for r in support_rows if r["stage"] == stage)
        print(f"  {_STAGE_LABEL[stage]:<16}  {atk_n:>9}  {sup_n:>8}")
    det_atk = sum(1 for r in attack_rows if r["stage"] == STAGE_DETECTED)
    det_sup = sum(1 for r in support_rows if r["stage"] == STAGE_DETECTED)
    print(f"  {'-'*16}  {'-'*9}  {'-'*8}")
    print(f"  {'DETECTED':<16}  {det_atk:>9}  {det_sup:>8}")
    print(f"  {'TOTAL':<16}  {len(attack_rows):>9}  {len(support_rows):>8}")


# ---------------------------------------------------------------------------
# Run-dir discovery
# ---------------------------------------------------------------------------

def find_most_recent_run() -> Path:
    """Most recent runs/kostenko_*/ with both v5_result.json and events.jsonl."""
    if not RUNS_DIR.is_dir():
        raise FileNotFoundError(f"No runs directory at {RUNS_DIR}")
    candidates = sorted(
        (
            p for p in RUNS_DIR.iterdir()
            if p.is_dir() and p.name.startswith("kostenko_")
            and (p / "v5_result.json").is_file()
            and (p / "events.jsonl").is_file()
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"No kostenko_* run with v5_result.json + events.jsonl in {RUNS_DIR}"
        )
    return candidates[0]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--run-dir", type=Path, default=None,
        help="Path to a run dir. Defaults to the most recent kostenko_* with full artifacts.",
    )
    parser.add_argument(
        "--case-file", type=Path, default=DEFAULT_KOSTENKO_KB,
        help="GT case file. Default: kostenko_knowledge_base.json",
    )
    args = parser.parse_args()

    run_dir = args.run_dir or find_most_recent_run()
    section("Axis 8 — Failure-mode auto-classifier")
    print(f"  Run:       {run_dir.name}")
    print(f"  Case file: {args.case_file}")

    case = _load_json(args.case_file)
    v5 = _load_json(run_dir / "v5_result.json")
    events = _load_events(run_dir)
    v4_path = run_dir / "v4_result.json"
    v4 = _load_json(v4_path) if v4_path.is_file() else None
    args_by_id = _build_args_by_id(case, v4)

    af = case.get("argumentation_framework", {})

    # Classify every GT attack
    attack_rows = [
        classify_attack(atk, v5, events, args_by_id)
        for atk in af.get("attack_relations", [])
    ]

    # Classify every expected pair from every GT support cluster
    # (expand each n-way cluster into C(n, 2) pairs)
    support_rows: list[dict] = []
    for sup in af.get("support_relations", []):
        members = sup.get("supporters", [])
        for pair in combinations(members, 2):
            support_rows.append(
                classify_support_pair(pair, sup, v5, events, args_by_id)
            )

    print_attack_classifications(attack_rows)
    print_support_classifications(support_rows)
    print_summary(attack_rows, support_rows)

    # Save the structured table for the thesis writeup
    out_path = run_dir / "axis8_failure_modes.json"
    out_path.write_text(json.dumps({
        "run_id": run_dir.name,
        "attacks": attack_rows,
        "supports": support_rows,
        "summary": {
            "attacks_total": len(attack_rows),
            "attacks_detected": sum(1 for r in attack_rows if r["stage"] == STAGE_DETECTED),
            "supports_total": len(support_rows),
            "supports_detected": sum(1 for r in support_rows if r["stage"] == STAGE_DETECTED),
            "by_stage": {
                _STAGE_LABEL[stage]: {
                    "attacks": sum(1 for r in attack_rows if r["stage"] == stage),
                    "supports": sum(1 for r in support_rows if r["stage"] == stage),
                }
                for stage in (
                    STAGE_GENERATION, STAGE_DETECTION,
                    STAGE_CONFIRMATION, STAGE_SEMANTICS, STAGE_DETECTED,
                )
            },
        },
    }, indent=2) + "\n")
    print()
    print(f"  Saved: {out_path}")


if __name__ == "__main__":
    main()
