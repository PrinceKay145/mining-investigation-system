"""
Tests for `scripts/classify_failure_modes.py` — Axis 8 failure-mode classifier.

Exercises every classification path with synthetic fixtures (no actual run
required). The four pipeline stages — Generation, Detection, Confirmation,
Semantics — each get a positive test that yields that classification, plus
the happy paths (DETECTED exact + direction_flipped / type_mismatch).
"""

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from classify_failure_modes import (  # noqa: E402
    STAGE_CONFIRMATION,
    STAGE_DETECTED,
    STAGE_DETECTION,
    STAGE_GENERATION,
    STAGE_SEMANTICS,
    _build_args_by_id,
    _find_pair_check_event,
    _find_v5_attack,
    _find_v5_support_pair,
    classify_attack,
    classify_support_pair,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _arg(id_: str, topic: str = "T") -> dict:
    return {"id": id_, "topic": topic}


def _pair_check_event(a: str, b: str, relation: str, rationale: str = "x") -> dict:
    return {
        "event": "v5_pair_check_done",
        "arg_a": a, "arg_b": b,
        "relation": relation, "rationale": rationale,
    }


def _gt_attack(id_: str, attacker: str, target: str, type_: str = "rebutting") -> dict:
    return {"id": id_, "attacker": attacker, "target": target, "type": type_}


# ---------------------------------------------------------------------------
# Helper-function unit tests
# ---------------------------------------------------------------------------

def test_find_pair_check_event_matches_either_order():
    events = [_pair_check_event("A", "B", "rebutting")]
    assert _find_pair_check_event("A", "B", events) is not None
    assert _find_pair_check_event("B", "A", events) is not None


def test_find_pair_check_event_returns_none_if_pair_not_checked():
    events = [_pair_check_event("C", "D", "support")]
    assert _find_pair_check_event("A", "B", events) is None


def test_find_v5_attack_returns_correct_direction():
    v5 = {"attack_relations": [
        {"id": "ATK-V5-001", "attacker": "U-A3", "target": "D-A5", "type": "rebutting"},
    ]}
    assert _find_v5_attack("U-A3", "D-A5", v5)["id"] == "ATK-V5-001"
    # Reverse direction should not match when exact_direction=True
    assert _find_v5_attack("D-A5", "U-A3", v5) is None


def test_find_v5_support_pair_matches_when_both_in_cluster():
    v5 = {"support_relations": [
        {"id": "SUP-V5-1", "supporters": ["U-A2", "K-A3", "D-A4"]},
    ]}
    assert _find_v5_support_pair("U-A2", "K-A3", v5) is not None
    assert _find_v5_support_pair("D-A4", "U-A2", v5) is not None
    # Member missing → no match
    assert _find_v5_support_pair("U-A2", "X-99", v5) is None


def test_build_args_by_id_unifies_expert_and_agent_args():
    case = {"arguments": [_arg("U-A1"), _arg("K-A1")]}
    v4 = {
        "agent_1_arguments": [_arg("agent_1_001")],
        "agent_3_arguments": [_arg("agent_3_001")],
        "agent_2_arguments": [],
        "agent_4_arguments": [],
    }
    idx = _build_args_by_id(case, v4)
    assert set(idx.keys()) == {"U-A1", "K-A1", "agent_1_001", "agent_3_001"}


# ---------------------------------------------------------------------------
# classify_attack — one test per stage
# ---------------------------------------------------------------------------

def test_classify_attack_generation_miss_when_attacker_absent():
    args_by_id = {"D-A5": _arg("D-A5")}
    out = classify_attack(_gt_attack("ATK-X", "U-A3", "D-A5"), v5={}, events=[],
                          args_by_id=args_by_id)
    assert out["stage"] == STAGE_GENERATION
    assert "U-A3" in out["reason"]


def test_classify_attack_detection_miss_when_topic_filter_excludes():
    """K-A7 (Explosion sequence) vs D-A8 (Explosion location) — the canonical ATK-4 case."""
    args_by_id = {
        "K-A7": _arg("K-A7", topic="Explosion sequence"),
        "D-A8": _arg("D-A8", topic="Explosion location"),
    }
    out = classify_attack(
        _gt_attack("ATK-4", "K-A7", "D-A8", type_="undercutting"),
        v5={"attack_relations": []},
        events=[],  # pair never reached LLM
        args_by_id=args_by_id,
    )
    assert out["stage"] == STAGE_DETECTION
    assert out["attacker_topic"] == "Explosion sequence"
    assert out["target_topic"] == "Explosion location"


def test_classify_attack_confirmation_miss_when_llm_returns_independent():
    """K-A4 / U-A3 — the canonical ATK-2 case (LLM said 'independent')."""
    args_by_id = {
        "K-A4": _arg("K-A4", topic="Ignition source"),
        "U-A3": _arg("U-A3", topic="Ignition source"),
    }
    events = [_pair_check_event("K-A4", "U-A3", "independent",
                                rationale="Both arguments address the same topic but...")]
    out = classify_attack(
        _gt_attack("ATK-2", "K-A4", "U-A3", type_="rebutting"),
        v5={"attack_relations": []},
        events=events,
        args_by_id=args_by_id,
    )
    assert out["stage"] == STAGE_CONFIRMATION
    assert out["llm_relation"] == "independent"


def test_classify_attack_confirmation_miss_when_llm_returns_support():
    """LLM says 'support' but GT expected 'rebutting' — still a confirmation miss."""
    args_by_id = {"A": _arg("A"), "B": _arg("B")}
    events = [_pair_check_event("A", "B", "support")]
    out = classify_attack(_gt_attack("X", "A", "B"), v5={}, events=events,
                          args_by_id=args_by_id)
    assert out["stage"] == STAGE_CONFIRMATION


def test_classify_attack_detected_exact_when_v5_matches_gt():
    """U-A3 → D-A5 (rebutting) — the canonical ATK-1 case."""
    args_by_id = {"U-A3": _arg("U-A3"), "D-A5": _arg("D-A5")}
    events = [_pair_check_event("U-A3", "D-A5", "rebutting")]
    v5 = {"attack_relations": [
        {"id": "ATK-V5-001", "attacker": "U-A3", "target": "D-A5", "type": "rebutting"},
    ]}
    out = classify_attack(_gt_attack("ATK-1", "U-A3", "D-A5", "rebutting"),
                          v5=v5, events=events, args_by_id=args_by_id)
    assert out["stage"] == STAGE_DETECTED
    assert out["form"] == "exact"


def test_classify_attack_detected_direction_flipped_when_v5_has_reverse():
    """v5 detected an attack but with attacker/target reversed compared to GT."""
    args_by_id = {"A": _arg("A"), "B": _arg("B")}
    events = [_pair_check_event("A", "B", "undercutting_b_to_a")]
    v5 = {"attack_relations": [
        # GT says A→B but v5 has B→A
        {"id": "ATK-V5-X", "attacker": "B", "target": "A", "type": "undercutting"},
    ]}
    out = classify_attack(_gt_attack("X", "A", "B", "undercutting"),
                          v5=v5, events=events, args_by_id=args_by_id)
    assert out["stage"] == STAGE_DETECTED
    assert out["form"] == "direction_flipped"


def test_classify_attack_detected_type_mismatch_when_v5_has_wrong_type():
    args_by_id = {"A": _arg("A"), "B": _arg("B")}
    events = [_pair_check_event("A", "B", "undercutting_a_to_b")]
    v5 = {"attack_relations": [
        # GT says rebutting; v5 has undercutting
        {"id": "ATK-V5-Y", "attacker": "A", "target": "B", "type": "undercutting"},
    ]}
    out = classify_attack(_gt_attack("X", "A", "B", "rebutting"),
                          v5=v5, events=events, args_by_id=args_by_id)
    assert out["stage"] == STAGE_DETECTED
    assert out["form"] == "type_mismatch"


def test_classify_attack_semantics_demotion_when_confirmed_but_not_in_v5():
    """LLM said attack relation, but v5_result has no matching attack in either direction."""
    args_by_id = {"A": _arg("A"), "B": _arg("B")}
    events = [_pair_check_event("A", "B", "rebutting")]
    v5 = {"attack_relations": []}  # confirmed but missing from output
    out = classify_attack(_gt_attack("X", "A", "B", "rebutting"),
                          v5=v5, events=events, args_by_id=args_by_id)
    assert out["stage"] == STAGE_SEMANTICS


# ---------------------------------------------------------------------------
# classify_support_pair — one test per stage
# ---------------------------------------------------------------------------

def _sup_cluster(id_: str, topic: str, members: list[str]) -> dict:
    return {"id": id_, "topic": topic, "supporters": members}


def test_classify_support_pair_detection_miss_on_topic_mismatch():
    """The canonical SUP-2 partial-miss case: U-A1 ('Ignition location') + K-A6 ('Explosion location')."""
    args_by_id = {
        "U-A1": _arg("U-A1", topic="Ignition location"),
        "K-A6": _arg("K-A6", topic="Explosion location"),
    }
    cluster = _sup_cluster("SUP-2", "Ignition location", ["U-A1", "K-A6", "D-A6"])
    out = classify_support_pair(
        ("U-A1", "K-A6"), cluster, v5={}, events=[], args_by_id=args_by_id,
    )
    assert out["stage"] == STAGE_DETECTION
    assert out["topics"] == ["Ignition location", "Explosion location"]


def test_classify_support_pair_confirmation_miss_when_llm_says_independent():
    args_by_id = {"A": _arg("A"), "B": _arg("B")}
    events = [_pair_check_event("A", "B", "independent")]
    cluster = _sup_cluster("SUP-X", "T", ["A", "B"])
    out = classify_support_pair(("A", "B"), cluster, v5={}, events=events,
                                args_by_id=args_by_id)
    assert out["stage"] == STAGE_CONFIRMATION
    assert "independent" in out["reason"]


def test_classify_support_pair_detected_when_in_v5_supports():
    args_by_id = {"U-A2": _arg("U-A2"), "K-A3": _arg("K-A3")}
    events = [_pair_check_event("U-A2", "K-A3", "support")]
    v5 = {"support_relations": [
        {"id": "SUP-V5-1", "supporters": ["U-A2", "K-A3"]},
    ]}
    cluster = _sup_cluster("SUP-1", "T", ["U-A2", "K-A3"])
    out = classify_support_pair(("U-A2", "K-A3"), cluster, v5=v5, events=events,
                                args_by_id=args_by_id)
    assert out["stage"] == STAGE_DETECTED


def test_classify_support_pair_semantics_demotion_when_confirmed_but_no_cluster_contains_both():
    args_by_id = {"A": _arg("A"), "B": _arg("B")}
    events = [_pair_check_event("A", "B", "support")]
    v5 = {"support_relations": [
        # A clustered separately from B
        {"id": "S1", "supporters": ["A", "C"]},
        {"id": "S2", "supporters": ["B", "D"]},
    ]}
    cluster = _sup_cluster("SUP-X", "T", ["A", "B"])
    out = classify_support_pair(("A", "B"), cluster, v5=v5, events=events,
                                args_by_id=args_by_id)
    assert out["stage"] == STAGE_SEMANTICS
