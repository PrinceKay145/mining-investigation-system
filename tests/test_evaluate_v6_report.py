"""
Tests for `scripts/evaluate_v6_report.py` — Axis 7 (v6 report judge).

Real OpenAI API calls are NOT made — `OpenAIClient` is replaced with a
fake whose `complete_json` returns a scripted `V6ReportJudgeResult`. The
tests verify:
  - Input formatters render structured artifacts into the prompt template.
  - The judge prompt renders end-to-end against a real (May-11) run dir.
  - Pydantic schema validation enforces the 1.0–5.0 score range.
  - `overall_score` is the computed mean of the five dimensions.
"""

import json
import sys
from pathlib import Path

import pytest

# evaluate_v6_report.py lives under scripts/
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from evaluate_v6_report import (  # noqa: E402
    build_judge_prompt,
    format_argument_inventory,
    format_attack_inventory,
    format_case_summary,
    format_investigation_questions,
)
from schema.judge_result import (  # noqa: E402
    MAX_SCORE,
    MIN_SCORE,
    RubricScore,
    V6ReportJudgeResult,
)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def _good_rubric(score: float = 4.0) -> RubricScore:
    return RubricScore(score=score, rationale="solid alignment with GT facts")


def _good_result(scores: tuple[float, ...] = (4.5, 4.0, 3.5, 4.0, 4.0)) -> V6ReportJudgeResult:
    fa, co, ci, na, de = scores
    return V6ReportJudgeResult(
        factual_accuracy=_good_rubric(fa),
        completeness=_good_rubric(co),
        citation_correctness=_good_rubric(ci),
        narrative_coherence=_good_rubric(na),
        defense_readiness=_good_rubric(de),
        overall_comments="Strongest on factual accuracy, weakest on citation correctness.",
        flagged_issues=["[K-A99] cited but not in inventory"],
    )


def test_rubric_score_rejects_out_of_range_below():
    with pytest.raises(Exception):  # pydantic ValidationError
        RubricScore(score=MIN_SCORE - 0.5, rationale="x" * 20)


def test_rubric_score_rejects_out_of_range_above():
    with pytest.raises(Exception):
        RubricScore(score=MAX_SCORE + 0.5, rationale="x" * 20)


def test_rubric_score_requires_substantive_rationale():
    with pytest.raises(Exception):
        RubricScore(score=3.0, rationale="ok")  # too short (< 10 chars)


def test_overall_score_is_computed_mean_of_five_dimensions():
    r = _good_result(scores=(5.0, 4.0, 3.0, 2.0, 1.0))
    assert r.overall_score == pytest.approx(3.0)


def test_flagged_issues_defaults_to_empty_list():
    r = V6ReportJudgeResult(
        factual_accuracy=_good_rubric(),
        completeness=_good_rubric(),
        citation_correctness=_good_rubric(),
        narrative_coherence=_good_rubric(),
        defense_readiness=_good_rubric(),
        overall_comments="report is fully filable with no edits needed",
    )
    assert r.flagged_issues == []


# ---------------------------------------------------------------------------
# Input formatters
# ---------------------------------------------------------------------------

def test_format_investigation_questions_numbers_each_entry():
    out = format_investigation_questions(["Cause of fire", "Methane source"])
    assert "1. Cause of fire" in out
    assert "2. Methane source" in out


def test_format_investigation_questions_handles_empty():
    assert "none" in format_investigation_questions([]).lower()


def test_format_case_summary_includes_case_metadata():
    case = {
        "metadata": {
            "case": "kostenko",
            "date": "2023-10-28",
            "location": "Karaganda",
            "longwall": "L-142",
            "sources": [
                {"id": "U", "name": "Usembekov",
                 "argument_ids_prefix": "U-A", "description": "first commission"},
            ],
        }
    }
    out = format_case_summary(case)
    assert "kostenko" in out
    assert "2023-10-28" in out
    assert "Karaganda" in out
    assert "L-142" in out
    assert "Usembekov" in out


def test_format_argument_inventory_lists_each_arg_with_id_and_claim_excerpt():
    case = {"arguments": [
        {"id": "U-A1", "source": "Usembekov", "claim": "Methane was the primary fuel"},
        {"id": "K-A1", "source": "Kolikov", "claim": "AFC sparking was the ignition source"},
    ]}
    out = format_argument_inventory(case, v4=None)
    assert "[U-A1]" in out
    assert "[K-A1]" in out
    assert "Usembekov" in out


def test_format_argument_inventory_includes_v4_agents_when_present():
    case = {"arguments": []}
    v4 = {
        "agent_1_arguments": [{"id": "agent_1_001", "claim": "Technical claim X"}],
        "agent_3_arguments": [{"id": "agent_3_002", "claim": "Challenge claim Y"}],
    }
    out = format_argument_inventory(case, v4=v4)
    assert "[agent_1_001]" in out
    assert "[agent_3_002]" in out


def test_format_attack_inventory_lists_attacks_and_supports():
    v5 = {
        "attack_relations": [
            {"id": "ATK-V5-001", "attacker": "U-A3", "target": "K-A4", "type": "rebutting"},
        ],
        "support_relations": [
            {"id": "SUP-V5-001", "supporters": ["U-A2", "K-A3"], "topic": "Methane source"},
        ],
    }
    out = format_attack_inventory(v5)
    assert "[ATK-V5-001]" in out
    assert "U-A3 → K-A4" in out
    assert "[SUP-V5-001]" in out
    assert "Methane source" in out


# ---------------------------------------------------------------------------
# End-to-end: prompt renders against a real run + minimal case file
# ---------------------------------------------------------------------------

def _write_fixture_run(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal run dir + case file fixture for testing."""
    run_dir = tmp_path / "fake_run"
    run_dir.mkdir()
    (run_dir / "report.md").write_text(
        "# Investigation Report\n\nMethane was the primary fuel [U-A1].\n"
    )
    (run_dir / "v5_result.json").write_text(json.dumps({
        "attack_relations": [],
        "support_relations": [],
    }))
    (run_dir / "v4_result.json").write_text(json.dumps({
        "agent_1_arguments": [{"id": "agent_1_001", "claim": "Tech claim"}],
        "agent_2_arguments": [],
        "agent_3_arguments": [],
        "agent_4_arguments": [],
    }))
    case_path = tmp_path / "case.json"
    case_path.write_text(json.dumps({
        "metadata": {
            "case": "kostenko", "date": "2023-10-28", "location": "Karaganda",
            "investigation_questions": ["Cause of fire", "Methane source"],
            "sources": [],
        },
        "arguments": [{"id": "U-A1", "source": "Usembekov", "claim": "Methane was primary"}],
    }))
    return run_dir, case_path


def test_build_judge_prompt_renders_all_required_inputs(tmp_path):
    run_dir, case_path = _write_fixture_run(tmp_path)
    prompt = build_judge_prompt(run_dir=run_dir, case_path=case_path)
    # The prompt should include the rubric (from the template)
    assert "Scoring rubric" in prompt
    # ... case metadata
    assert "kostenko" in prompt
    # ... the rendered investigation questions
    assert "Cause of fire" in prompt
    # ... the argument inventory (U-A1 + agent_1_001)
    assert "[U-A1]" in prompt
    assert "[agent_1_001]" in prompt
    # ... the actual report content
    assert "Methane was the primary fuel" in prompt


def test_build_judge_prompt_handles_missing_v4_result(tmp_path):
    """v4_result.json is optional — only v5_result.json + report.md are required."""
    run_dir, case_path = _write_fixture_run(tmp_path)
    (run_dir / "v4_result.json").unlink()  # remove
    # Should not raise
    prompt = build_judge_prompt(run_dir=run_dir, case_path=case_path)
    assert "[U-A1]" in prompt
    # agent_1_001 should NOT appear since v4 result is missing
    assert "agent_1_001" not in prompt
