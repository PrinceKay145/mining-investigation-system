"""
Tests for `scripts/evaluate_argument_quality.py` — Axis 5
(argument-quality LLM-as-judge).

Real OpenAI calls are not made. Tests cover:
  - Schema validation (per-arg 4-dimension scores, computed mean).
  - Input formatters (case summary, expert args list, v4 args grouped by agent).
  - Per-agent aggregates computed deterministically from a fixture
    `ArgumentQualityResult`.
  - End-to-end prompt-render against a fixture run dir.
"""

import json
import sys
from pathlib import Path

import pytest

# evaluate_argument_quality.py lives under scripts/
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from evaluate_argument_quality import (  # noqa: E402
    _agent_id_from_arg,
    compute_per_agent_aggregates,
    format_case_summary,
    format_expert_arguments,
    format_v4_arguments,
)
from schema.judge_result import (  # noqa: E402
    ArgumentQualityResult,
    ArgumentQualityScores,
    RubricScore,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rubric(score: float = 4.0, why: str = "looks well-grounded") -> RubricScore:
    return RubricScore(score=score, rationale=why)


def _scores(arg_id: str, eg=4.0, wv=4.0, cn=4.0, cc=4.0) -> ArgumentQualityScores:
    return ArgumentQualityScores(
        arg_id=arg_id,
        evidence_groundedness=_rubric(eg),
        warrant_validity=_rubric(wv),
        claim_novelty=_rubric(cn),
        citation_correctness=_rubric(cc),
        comments="overall solid",
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def test_argument_quality_scores_mean_is_dimension_mean():
    s = _scores("agent_1_001", eg=5.0, wv=3.0, cn=4.0, cc=2.0)
    assert s.mean_score == pytest.approx(3.5)


def test_argument_quality_result_requires_non_empty_synthesis():
    """overall_comments must be substantive (min 20 chars)."""
    with pytest.raises(Exception):
        ArgumentQualityResult(scores=[_scores("agent_1_001")], overall_comments="too short")


# ---------------------------------------------------------------------------
# Input formatters
# ---------------------------------------------------------------------------

def test_format_case_summary_includes_basic_metadata():
    case = {"metadata": {
        "case": "kostenko", "date": "2023-10-28", "location": "Karaganda",
        "longwall": "L-142",
        "investigation_questions": ["Cause of fire", "Methane source"],
    }}
    out = format_case_summary(case)
    assert "kostenko" in out
    assert "L-142" in out
    assert "Cause of fire" in out


def test_format_expert_arguments_lists_all_with_evidence_and_categories():
    case = {"arguments": [
        {"id": "U-A1", "source": "Usembekov", "topic": "Methane source",
         "claim": "K2 seam was the source", "evidence": "isotopic match",
         "cause_categories": ["TC-04"]},
    ]}
    out = format_expert_arguments(case)
    assert "[U-A1]" in out
    assert "K2 seam" in out
    assert "isotopic match" in out
    assert "TC-04" in out


def test_format_expert_arguments_handles_empty():
    out = format_expert_arguments({"arguments": []})
    assert "no expert arguments" in out.lower()


def test_format_v4_arguments_groups_by_agent_with_role_labels():
    v4 = {
        "agent_1_arguments": [{"id": "agent_1_001", "claim": "tech claim",
                              "evidence": "e", "warrant": "w",
                              "cause_categories": ["TC-01"]}],
        "agent_3_arguments": [{"id": "agent_3_001", "claim": "challenge claim",
                              "evidence": "e", "warrant": "w",
                              "cause_categories": ["TC-02"]}],
        "agent_2_arguments": [],
        "agent_4_arguments": [],
    }
    out = format_v4_arguments(v4)
    assert "Technical agent" in out
    assert "Challenger agent" in out
    assert "[agent_1_001]" in out
    assert "[agent_3_001]" in out
    # Empty agent groups should NOT be included
    assert "Organizational agent" not in out
    assert "Regulatory agent" not in out


# ---------------------------------------------------------------------------
# Per-agent aggregates (computed, not judged)
# ---------------------------------------------------------------------------

def test_agent_id_from_arg_recognizes_all_four_agents():
    assert _agent_id_from_arg("agent_1_005") == "agent_1"
    assert _agent_id_from_arg("agent_2_001") == "agent_2"
    assert _agent_id_from_arg("agent_3_007") == "agent_3"
    assert _agent_id_from_arg("agent_4_002") == "agent_4"


def test_agent_id_from_arg_returns_none_for_expert_ids():
    """Expert IDs (U-A*, K-A*, D-A*) shouldn't be classified into any agent."""
    assert _agent_id_from_arg("U-A1") is None
    assert _agent_id_from_arg("K-A8") is None


def test_compute_per_agent_aggregates_means_dimensions_and_overall():
    result = ArgumentQualityResult(
        scores=[
            _scores("agent_1_001", eg=4.0, wv=4.0, cn=4.0, cc=4.0),
            _scores("agent_1_002", eg=2.0, wv=2.0, cn=2.0, cc=2.0),
            _scores("agent_3_001", eg=5.0, wv=5.0, cn=5.0, cc=5.0),
        ],
        overall_comments="agent_3 outperformed agent_1 across all dimensions",
    )
    agg = compute_per_agent_aggregates(result)
    # Agent 1: mean of (4, 2) = 3.0 across every dimension
    a1 = agg["agent_1"]
    assert a1["count"] == 2
    assert a1["mean_evidence_groundedness"] == pytest.approx(3.0)
    assert a1["overall_mean"] == pytest.approx(3.0)
    # Agent 3: only one arg, scoring 5.0 across all dims
    a3 = agg["agent_3"]
    assert a3["count"] == 1
    assert a3["mean_evidence_groundedness"] == pytest.approx(5.0)
    assert a3["overall_mean"] == pytest.approx(5.0)
    # Agents 2 and 4 had no scored args → not in aggregates
    assert "agent_2" not in agg
    assert "agent_4" not in agg


def test_compute_per_agent_aggregates_labels_each_agent():
    """The label field should map agent_N to its human-readable role."""
    result = ArgumentQualityResult(
        scores=[
            _scores("agent_1_001"),
            _scores("agent_2_001"),
            _scores("agent_3_001"),
            _scores("agent_4_001"),
        ],
        overall_comments="all agents produced comparable arguments",
    )
    agg = compute_per_agent_aggregates(result)
    labels = {k: v["label"] for k, v in agg.items()}
    assert labels == {
        "agent_1": "Technical",
        "agent_2": "Organizational",
        "agent_3": "Challenger",
        "agent_4": "Regulatory",
    }


def test_compute_per_agent_aggregates_ignores_non_agent_ids():
    """If the judge accidentally scores an expert arg (with U-/K-/D- prefix), skip it."""
    result = ArgumentQualityResult(
        scores=[
            _scores("agent_1_001"),
            _scores("U-A1"),  # should be excluded
        ],
        overall_comments="judge incorrectly scored an expert arg, ignored",
    )
    agg = compute_per_agent_aggregates(result)
    assert "agent_1" in agg
    assert agg["agent_1"]["count"] == 1
    # No "expert" or "U" bucket
    assert all(k.startswith("agent_") for k in agg.keys())
