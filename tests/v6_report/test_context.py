"""Tests for v6 context-building helpers (pure functions, no I/O)."""

from kb.loader import load_case_file, load_regulatory_kb
from schema.argument import Argument
from schema.classification import ClassificationResult
from schema.precedent_match import PrecedentMatchResult, PrecedentMatch
from schema.v5_result import V5Result
from v2_identification import classify
from v3_precedent_matching import match_precedents
from v6_report.context import (
    build_context,
    format_attacks_summary,
    format_classification_summary,
    format_expert_sources,
    format_investigation_questions,
    format_open_questions,
    format_precedent_summary,
    format_regulations_summary,
)


def test_format_investigation_questions_basic():
    out = format_investigation_questions(["First?", "Second?"])
    assert "1. First?" in out and "2. Second?" in out


def test_format_investigation_questions_empty():
    assert "none recorded" in format_investigation_questions([])


def test_format_expert_sources_includes_full_names():
    sources = [
        {"id": "U", "full_name": "Usembekov", "affiliation": "X", "role": "Y"},
    ]
    out = format_expert_sources(sources)
    assert "Usembekov" in out
    assert "U" in out


def test_format_classification_resolves_cause_labels(regulatory_kb_path):
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    c = ClassificationResult(
        primary_type="methane_explosion",
        secondary_types=["underground_gas_fire"],
        cause_profile={"TC-01": 7, "TC-02": 5},
    )
    out = format_classification_summary(c, reg_kb.cause_categories)
    assert "TC-01" in out and "methane_accumulation" in out
    assert "TC-02" in out


def test_format_precedent_summary_includes_mine_names(regulatory_kb_path, kostenko_kb_path):
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    classif = classify(case.arguments, reg_kb.regulations)
    match = match_precedents(classif, reg_kb.precedents)
    out = format_precedent_summary(match, reg_kb.precedents)
    assert "Listvyazhnaya" in out
    assert "overlap" in out


def test_format_attacks_summary_lists_each():
    from schema.ground_truth import AttackRelation, AttackType
    v5 = V5Result(
        attack_relations=[
            AttackRelation(id="ATK-V5-001", attacker="A1", target="A2",
                           type=AttackType.REBUTTING, description="x"),
            AttackRelation(id="ATK-V5-002", attacker="A2", target="A1",
                           type=AttackType.REBUTTING, description="y"),
        ],
    )
    out = format_attacks_summary(v5)
    assert "ATK-V5-001" in out and "ATK-V5-002" in out
    assert "2 attacks" in out


def test_format_attacks_summary_empty():
    out = format_attacks_summary(V5Result())
    assert "no attacks" in out.lower()


def test_format_open_questions_from_kostenko(kostenko_kb_path):
    case = load_case_file(kostenko_kb_path)
    out = format_open_questions(case)
    assert "OQ-1" in out and "OQ-5" in out


def test_format_regulations_summary_lists_all(regulatory_kb_path):
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    out = format_regulations_summary(reg_kb.regulations)
    assert "REG-01" in out and "REG-14" in out


def test_build_context_returns_all_keys(regulatory_kb_path, kostenko_kb_path):
    """The context dict must have one key per {{ var }} in v6_report.md."""
    from schema.v4_result import V4Result

    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    classif = classify(case.arguments, reg_kb.regulations)
    match = match_precedents(classif, reg_kb.precedents)
    v4 = V4Result()  # empty agents — context should still build
    v5 = V5Result(grounded_extension=["U-A1"], accepted=["U-A1"])

    ctx = build_context(
        case=case,
        classification=classif,
        match_result=match,
        v4_result=v4,
        v5_result=v5,
        cause_categories=reg_kb.cause_categories,
        precedents=reg_kb.precedents,
        regulations=reg_kb.regulations,
    )
    expected_keys = {
        "case_name", "case_date", "case_location",
        "investigation_questions", "expert_sources",
        "classification_summary", "precedent_summary",
        "all_arguments_summary",
        "attacks_summary", "supports_summary",
        "accepted_summary", "ambiguous_summary", "rejected_summary",
        "open_questions", "regulations_summary",
    }
    assert set(ctx.keys()) == expected_keys
    assert ctx["case_name"] == "Kostenko Mine Explosion"
