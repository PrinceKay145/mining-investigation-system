"""Tests for v4 context formatting helpers — pure functions, no I/O."""

import json

from kb.loader import load_regulatory_kb, load_case_file
from schema.argument import Argument
from schema.classification import ClassificationResult
from schema.precedent_match import PrecedentMatchResult, PrecedentMatch
from v2_identification import classify
from v3_precedent_matching import match_precedents
from v4_agents.context import (
    extract_canonical_topics,
    format_agent_arguments,
    format_cause_taxonomy,
    format_classification,
    format_evidence_arguments,
    format_investigation_questions,
    format_precedent_matches,
    format_regulatory_requirements,
)


# ---------------------------------------------------------------------------
# Investigation questions
# ---------------------------------------------------------------------------

def test_format_investigation_questions_basic():
    out = format_investigation_questions(["First?", "Second?"])
    assert "1. First?" in out
    assert "2. Second?" in out


def test_format_investigation_questions_empty():
    assert "no investigation questions" in format_investigation_questions([])


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_format_classification_includes_primary_and_secondary():
    c = ClassificationResult(
        primary_type="methane_explosion",
        secondary_types=["underground_gas_fire"],
        cause_profile={"TC-01": 5, "TC-02": 2},
    )
    out = format_classification(c)
    assert "methane_explosion" in out
    assert "underground_gas_fire" in out
    assert "TC-01" in out
    assert "TC-02" in out


def test_format_classification_with_taxonomy_labels(regulatory_kb_path):
    """When taxonomy is provided, cause IDs gain their label for readability."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    c = ClassificationResult(
        primary_type="methane_explosion",
        cause_profile={"TC-01": 5},
    )
    out = format_classification(c, cause_categories=reg_kb.cause_categories)
    assert "TC-01 methane_accumulation" in out


# ---------------------------------------------------------------------------
# Precedent matches
# ---------------------------------------------------------------------------

def test_format_precedent_matches_empty(regulatory_kb_path):
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    empty = PrecedentMatchResult(
        matches=[],
        primary_type="x",
        secondary_types=[],
        total_precedents=11,
        filtered_count=0,
    )
    out = format_precedent_matches(empty, reg_kb.precedents)
    assert "11 precedents" in out
    assert "none matched" in out


def test_format_precedent_matches_includes_mine_name(regulatory_kb_path, kostenko_kb_path):
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    classif = classify(case.arguments, reg_kb.regulations)
    match = match_precedents(classif, reg_kb.precedents)

    out = format_precedent_matches(match, reg_kb.precedents)
    assert "Listvyazhnaya" in out
    assert "Alardinskaya" in out
    assert "overlap_score" in out


# ---------------------------------------------------------------------------
# Evidence arguments
# ---------------------------------------------------------------------------

def test_format_evidence_arguments_round_trip(kostenko_kb_path):
    case = load_case_file(kostenko_kb_path)
    out = format_evidence_arguments(case.arguments)
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert len(parsed) == 21
    assert parsed[0]["id"] == case.arguments[0].id


# ---------------------------------------------------------------------------
# Cause taxonomy
# ---------------------------------------------------------------------------

def test_format_cause_taxonomy_groups_by_tier(regulatory_kb_path):
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    out = format_cause_taxonomy(reg_kb.cause_categories)
    assert "Technical causes" in out
    assert "Organizational causes" in out
    assert "TC-01" in out
    assert "OC-01" in out
    # Technical section should appear before organizational
    assert out.index("TC-01") < out.index("OC-01")


# ---------------------------------------------------------------------------
# Regulatory requirements
# ---------------------------------------------------------------------------

def test_format_regulatory_requirements_includes_all(regulatory_kb_path):
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    out = format_regulatory_requirements(reg_kb.regulations)
    assert "REG-01" in out
    assert "REG-14" in out


# ---------------------------------------------------------------------------
# Canonical topics
# ---------------------------------------------------------------------------

def test_extract_canonical_topics_kostenko(kostenko_kb_path):
    case = load_case_file(kostenko_kb_path)
    topics = extract_canonical_topics(case.arguments)
    # Kostenko has 10 unique topics across 21 arguments
    assert len(topics) == 10
    assert "Ignition source" in topics
    assert "Methane source" in topics
    assert "Ventilation" in topics
    # Sorted
    assert topics == sorted(topics)


def test_extract_canonical_topics_dedupes():
    args = [
        _arg("A1", "Ignition source"),
        _arg("A2", "Ignition source"),
        _arg("A3", "Ventilation"),
    ]
    assert extract_canonical_topics(args) == ["Ignition source", "Ventilation"]


def _arg(arg_id: str, topic: str) -> Argument:
    return Argument(
        id=arg_id, source="X", topic=topic,
        claim="c", evidence="e", warrant="w",
        confidence=0.5, cause_categories=["TC-01"],
    )


# ---------------------------------------------------------------------------
# Agent argument serialization
# ---------------------------------------------------------------------------

def test_format_agent_arguments_round_trip():
    args = [_arg("agent_1_001", "Ignition source")]
    out = format_agent_arguments(args)
    parsed = json.loads(out)
    assert parsed[0]["id"] == "agent_1_001"
    assert parsed[0]["topic"] == "Ignition source"
