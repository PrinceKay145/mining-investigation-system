"""
Tests for `scripts/evaluate_stability.py` — Axis 2 multi-run stability.

Tests focus on the pure-function helpers (Jaccard, per-aspect stability,
per-argument bucket consistency) using synthetic fixture dicts in place
of real v5_result.json files.
"""

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from evaluate_stability import (  # noqa: E402
    jaccard,
    per_argument_bucket_consistency,
    stability_for_attacks,
    stability_for_bucket,
    stability_for_supports,
)


# ---------------------------------------------------------------------------
# Jaccard
# ---------------------------------------------------------------------------

def test_jaccard_identical_sets_is_one():
    assert jaccard({"a", "b", "c"}, {"a", "b", "c"}) == 1.0


def test_jaccard_disjoint_sets_is_zero():
    assert jaccard({"a"}, {"b"}) == 0.0


def test_jaccard_partial_overlap():
    """|{a,b} ∩ {b,c}| / |{a,b,c}| = 1/3."""
    assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)


def test_jaccard_both_empty_returns_one():
    """Degenerate identity case: empty equals empty."""
    assert jaccard(set(), set()) == 1.0


# ---------------------------------------------------------------------------
# Bucket stability (Jaccard on accepted/rejected/ambiguous sets)
# ---------------------------------------------------------------------------

def _run(accepted=None, rejected=None, ambiguous=None,
         attacks=None, supports=None) -> dict:
    return {
        "accepted": accepted or [],
        "rejected": rejected or [],
        "ambiguous": ambiguous or [],
        "attack_relations": attacks or [],
        "support_relations": supports or [],
    }


def test_stability_for_bucket_perfect_when_all_runs_identical():
    runs = [
        _run(accepted=["A", "B", "C"]),
        _run(accepted=["A", "B", "C"]),
        _run(accepted=["A", "B", "C"]),
    ]
    result = stability_for_bucket(runs, "accepted")
    assert result["mean"] == 1.0
    assert result["std"] == 0.0
    assert result["n"] == 3  # C(3, 2) pairs


def test_stability_for_bucket_low_when_runs_diverge():
    runs = [
        _run(accepted=["A", "B"]),
        _run(accepted=["C", "D"]),
    ]
    result = stability_for_bucket(runs, "accepted")
    assert result["mean"] == 0.0  # disjoint


def test_stability_for_bucket_partial_overlap():
    runs = [
        _run(accepted=["A", "B", "C"]),
        _run(accepted=["B", "C", "D"]),
    ]
    # |{A,B,C} ∩ {B,C,D}| / |{A,B,C,D}| = 2/4 = 0.5
    result = stability_for_bucket(runs, "accepted")
    assert result["mean"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Attack-edge and support-cluster stability
# ---------------------------------------------------------------------------

def _atk(attacker: str, target: str, type_: str = "rebutting") -> dict:
    return {"attacker": attacker, "target": target, "type": type_}


def test_stability_for_attacks_identical_edges():
    edges = [_atk("A", "B"), _atk("C", "D", "undercutting")]
    runs = [_run(attacks=edges), _run(attacks=edges)]
    result = stability_for_attacks(runs)
    assert result["mean"] == 1.0


def test_stability_for_attacks_treats_type_as_part_of_identity():
    """(A→B, rebutting) and (A→B, undercutting) are DIFFERENT edges for stability purposes."""
    runs = [
        _run(attacks=[_atk("A", "B", "rebutting")]),
        _run(attacks=[_atk("A", "B", "undercutting")]),
    ]
    result = stability_for_attacks(runs)
    # No overlap in (attacker, target, type) tuples
    assert result["mean"] == 0.0


def test_stability_for_supports_canonicalizes_member_order():
    """Support clusters should be compared as unordered sets of members."""
    runs = [
        _run(supports=[{"supporters": ["A", "B", "C"]}]),
        _run(supports=[{"supporters": ["C", "B", "A"]}]),  # same members, different order
    ]
    result = stability_for_supports(runs)
    assert result["mean"] == 1.0


def test_stability_for_supports_different_clusters_are_different():
    runs = [
        _run(supports=[{"supporters": ["A", "B"]}]),
        _run(supports=[{"supporters": ["A", "C"]}]),
    ]
    result = stability_for_supports(runs)
    assert result["mean"] == 0.0


# ---------------------------------------------------------------------------
# Per-argument bucket consistency
# ---------------------------------------------------------------------------

def test_per_argument_bucket_consistency_perfect_stability():
    runs = [
        _run(accepted=["A"], rejected=["B"], ambiguous=["C"]),
        _run(accepted=["A"], rejected=["B"], ambiguous=["C"]),
    ]
    result = per_argument_bucket_consistency(runs)
    assert result["summary"]["total_arguments"] == 3
    assert result["summary"]["stable_arguments"] == 3
    assert result["summary"]["flipping_arguments"] == 0
    assert result["summary"]["stability_rate"] == 1.0


def test_per_argument_bucket_consistency_detects_flipping():
    """Argument X appears in 'accepted' in run 1 but 'ambiguous' in run 2 — flipping."""
    runs = [
        _run(accepted=["A", "X"], ambiguous=["B"]),
        _run(accepted=["A"], ambiguous=["X", "B"]),
    ]
    result = per_argument_bucket_consistency(runs)
    stable_ids = set(result["always_same_bucket"])
    flipping_ids = {f["arg_id"] for f in result["flipping"]}
    assert "A" in stable_ids
    assert "B" in stable_ids
    assert "X" in flipping_ids


def test_per_argument_bucket_consistency_majority_share():
    """3 runs: arg X is accepted in 2 of 3, ambiguous in 1 of 3 → majority=accepted, share=2/3."""
    runs = [
        _run(accepted=["X"]),
        _run(accepted=["X"]),
        _run(ambiguous=["X"]),
    ]
    result = per_argument_bucket_consistency(runs)
    flipping = result["flipping"]
    assert len(flipping) == 1
    assert flipping[0]["arg_id"] == "X"
    assert flipping[0]["majority"] == "accepted"
    assert flipping[0]["majority_share"] == pytest.approx(2 / 3)
