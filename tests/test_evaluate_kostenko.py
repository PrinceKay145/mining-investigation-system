"""
Tests for `scripts/evaluate_kostenko.py` helpers.

Currently focuses on Axis 6 (per-expert Jaccard agreement) — the rest of
the script is integration-driven and tested via the canonical Kostenko run.
"""

import sys
from pathlib import Path

# evaluate_kostenko.py lives under scripts/ — make it importable as a module
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from evaluate_kostenko import (  # noqa: E402
    _expert_from_id,
    _interpret_spread,
    per_expert_agreement,
)


# ---------------------------------------------------------------------------
# _expert_from_id
# ---------------------------------------------------------------------------

def test_expert_from_id_recognizes_all_three_prefixes():
    assert _expert_from_id("U-A1") == "Usembekov"
    assert _expert_from_id("K-A8") == "Kolikov"
    assert _expert_from_id("D-A9") == "DMT"


def test_expert_from_id_returns_none_for_agent_ids():
    assert _expert_from_id("agent_1_001") is None
    assert _expert_from_id("agent_3_007") is None


# ---------------------------------------------------------------------------
# per_expert_agreement — happy paths
# ---------------------------------------------------------------------------

def _case(args: list[str]) -> dict:
    return {"arguments": [{"id": a} for a in args]}


def _v5(accepted: list[str], ambiguous: list[str] = None, rejected: list[str] = None) -> dict:
    return {
        "accepted": accepted,
        "ambiguous": ambiguous or [],
        "rejected": rejected or [],
    }


def test_per_expert_agreement_groups_args_by_id_prefix():
    case = _case(["U-A1", "U-A2", "K-A1", "K-A2", "K-A3", "D-A1", "agent_1_001"])
    v5 = _v5(accepted=[])
    rep = per_expert_agreement(v5, case)
    counts = {r["expert"]: r["expert_arg_count"] for r in rep["rows"]}
    assert counts == {"Usembekov": 2, "Kolikov": 3, "DMT": 1}


def test_per_expert_agreement_perfect_alignment_with_one_expert():
    """All Usembekov args accepted, no Kolikov/DMT — biased toward Usembekov."""
    case = _case(["U-A1", "U-A2", "K-A1", "D-A1"])
    v5 = _v5(accepted=["U-A1", "U-A2"], rejected=["K-A1", "D-A1"])
    rep = per_expert_agreement(v5, case)
    by_expert = {r["expert"]: r for r in rep["rows"]}
    assert by_expert["Usembekov"]["jaccard"] == 1.0
    assert by_expert["Usembekov"]["coverage_of_expert"] == 1.0
    assert by_expert["Kolikov"]["jaccard"] == 0.0
    assert by_expert["DMT"]["jaccard"] == 0.0
    assert rep["spread"] == 1.0
    assert "BIASED" in rep["interpretation"]
    assert "Usembekov" in rep["interpretation"]


def test_per_expert_agreement_balanced_synthesis():
    """Equal coverage across all three experts — the strong thesis story."""
    case = _case(["U-A1", "U-A2", "K-A1", "K-A2", "D-A1", "D-A2"])
    # Accept exactly one from each expert
    v5 = _v5(accepted=["U-A1", "K-A1", "D-A1"])
    rep = per_expert_agreement(v5, case)
    jaccards = {r["expert"]: r["jaccard"] for r in rep["rows"]}
    # All three should have the same Jaccard
    assert len({round(j, 6) for j in jaccards.values()}) == 1
    assert rep["spread"] == 0.0
    assert "BALANCED" in rep["interpretation"]


def test_per_expert_agreement_records_per_bucket_counts():
    """The accepted/ambiguous/rejected breakdown for each expert is preserved."""
    case = _case(["U-A1", "U-A2", "U-A3", "U-A4"])
    v5 = _v5(
        accepted=["U-A1"],
        ambiguous=["U-A2", "U-A3"],
        rejected=["U-A4"],
    )
    rep = per_expert_agreement(v5, case)
    row = next(r for r in rep["rows"] if r["expert"] == "Usembekov")
    assert row["accepted_count"] == 1
    assert row["ambiguous_count"] == 2
    assert row["rejected_count"] == 1


def test_per_expert_agreement_ignores_agent_ids():
    """Agent-sourced arguments don't get bucketed into any expert."""
    case = _case(["U-A1", "agent_1_001", "agent_2_002"])
    v5 = _v5(accepted=["U-A1", "agent_1_001", "agent_2_002"])
    rep = per_expert_agreement(v5, case)
    by_expert = {r["expert"]: r for r in rep["rows"]}
    assert by_expert["Usembekov"]["expert_arg_count"] == 1
    assert by_expert["Kolikov"]["expert_arg_count"] == 0
    assert by_expert["DMT"]["expert_arg_count"] == 0


# ---------------------------------------------------------------------------
# _interpret_spread thresholds
# ---------------------------------------------------------------------------

def _row(expert: str, jaccard: float, n: int = 4) -> dict:
    return {
        "expert": expert,
        "jaccard": jaccard,
        "expert_arg_count": n,
    }


def test_interpret_spread_large_spread_calls_it_biased():
    rows = [_row("U", 0.8), _row("K", 0.2), _row("D", 0.1)]
    s = _interpret_spread(0.7, rows)
    assert "BIASED" in s
    assert "U" in s


def test_interpret_spread_tiny_spread_calls_it_balanced():
    rows = [_row("U", 0.5), _row("K", 0.5), _row("D", 0.5)]
    s = _interpret_spread(0.02, rows)
    assert "BALANCED" in s


def test_interpret_spread_handles_no_expert_args():
    """If no expert has any arguments, the interpretation should say so."""
    rows = [_row("U", 0.0, n=0), _row("K", 0.0, n=0), _row("D", 0.0, n=0)]
    s = _interpret_spread(0.0, rows)
    assert "NO_EXPERTS" in s
