"""
Tests for KB loader, store, and referential integrity.

Path resolution comes from the shared conftest.py fixtures:
  regulatory_kb_path, kostenko_kb_path, kostenko_with_bad_cause_id.

The Kostenko KB carries permanent cause_categories as of the 2026-04-27
backfill, so no backfill_map is needed for normal loads. Bad-data tests
use the kostenko_with_bad_cause_id fixture (a tmp_path copy with one
argument's cause_categories set to a dangling 'TC-99').
"""

import json

from kb.loader import load_regulatory_kb, load_case_file, check_integrity
from kb.store import KnowledgeBase


# ===========================================================================
# Loader tests
# ===========================================================================

def test_load_regulatory_kb(regulatory_kb_path):
    data = load_regulatory_kb(regulatory_kb_path)
    assert len(data.cause_categories) == 23
    assert len(data.accident_types) == 8
    assert len(data.regulations) == 14
    assert len(data.precedents) == 11
    assert len(data.industry_statistics) == 5


def test_regulatory_kb_cause_ids(regulatory_kb_path):
    data = load_regulatory_kb(regulatory_kb_path)
    assert "TC-01" in data.cause_categories
    assert "OC-01" in data.cause_categories
    assert "TC-13" in data.cause_categories
    assert "OC-10" in data.cause_categories


def test_regulatory_kb_regulation_ids(regulatory_kb_path):
    data = load_regulatory_kb(regulatory_kb_path)
    assert "REG-01" in data.regulations
    assert "REG-14" in data.regulations


def test_regulatory_kb_precedent_types(regulatory_kb_path):
    data = load_regulatory_kb(regulatory_kb_path)
    types = {p.accident_type for p in data.precedents}
    assert "methane_explosion" in types
    assert "rock_burst" in types
    assert "endogenous_fire" in types


def test_load_case_file(kostenko_kb_path):
    case = load_case_file(kostenko_kb_path)
    assert len(case.arguments) == 21
    assert len(case.ground_truth.attack_relations) == 4
    assert len(case.ground_truth.support_relations) == 5
    assert len(case.ground_truth.open_questions) == 5


def test_load_case_file_arguments_have_cause_categories(kostenko_kb_path):
    """All 21 Kostenko arguments must carry cause_categories after backfill."""
    case = load_case_file(kostenko_kb_path)
    for arg in case.arguments:
        assert arg.cause_categories, f"{arg.id} has empty cause_categories"


def test_load_case_file_without_categories_fails(tmp_path):
    """Loader must reject arguments missing both cause_categories and backfill."""
    minimal = {
        "metadata": {"case": "Synthetic", "date": "2026-01-01"},
        "arguments": [
            {
                "id": "X-A1",
                "source": "X",
                "topic": "test",
                "claim": "test claim",
                "evidence": "test evidence",
                "warrant": "test warrant",
                "confidence": 0.5,
                # cause_categories omitted
            }
        ],
        "argumentation_framework": {
            "attack_relations": [],
            "support_relations": [],
            "open_questions": [],
        },
    }
    path = tmp_path / "no_categories.json"
    with open(path, "w") as f:
        json.dump(minimal, f)

    try:
        load_case_file(path)
        assert False, "Should raise ValueError for missing cause_categories"
    except ValueError as e:
        assert "cause_categories" in str(e)


def test_case_file_metadata(kostenko_kb_path):
    case = load_case_file(kostenko_kb_path)
    assert case.metadata.case == "Kostenko Mine Explosion"
    assert case.metadata.date == "2023-10-28"
    assert len(case.metadata.sources) == 3
    assert case.metadata.extra is not None
    assert case.metadata.extra.get("longwall") == "48K3-Z"


# ===========================================================================
# Referential integrity tests
# ===========================================================================

def test_integrity_regulatory_only(regulatory_kb_path):
    """Regulatory KB should have zero integrity errors internally."""
    data = load_regulatory_kb(regulatory_kb_path)
    errors = check_integrity(data)
    assert errors == [], f"Expected no errors, got: {errors}"


def test_integrity_with_valid_case(regulatory_kb_path, kostenko_kb_path):
    """Kostenko KB (with permanent cause_categories) passes integrity check."""
    data = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    errors = check_integrity(data, case_file=case)
    assert errors == [], f"Expected no errors, got: {errors}"


def test_integrity_catches_bad_cause_id(regulatory_kb_path, kostenko_with_bad_cause_id):
    """Dangling cause_category reference should be caught."""
    data = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_with_bad_cause_id)
    errors = check_integrity(data, case_file=case)
    assert len(errors) == 1
    assert errors[0].bad_ref == "TC-99"
    assert errors[0].entity_id == "U-A1"


def test_integrity_checks_attack_refs(regulatory_kb_path, kostenko_kb_path):
    """Ground truth attacker/target must reference existing argument IDs."""
    data = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    arg_ids = {a.id for a in case.arguments}
    for atk in case.ground_truth.attack_relations:
        assert atk.attacker in arg_ids
        assert atk.target in arg_ids
    errors = check_integrity(data, case_file=case)
    assert errors == []


# ===========================================================================
# Store tests
# ===========================================================================

def test_store_from_files(regulatory_kb_path, kostenko_kb_path):
    kb = KnowledgeBase.from_files(
        regulatory_path=regulatory_kb_path,
        case_path=kostenko_kb_path,
        case_name="kostenko",
    )
    assert "kostenko" in kb.case_files
    assert len(kb.cause_categories) == 23
    assert len(kb.precedents) == 11


def test_store_lookups(regulatory_kb_path):
    kb = KnowledgeBase.from_files(regulatory_path=regulatory_kb_path)
    cat = kb.get_cause_category("TC-01")
    assert cat is not None
    assert cat.label == "methane_accumulation"

    reg = kb.get_regulation("REG-05")
    assert reg is not None
    assert "explosion-proof" in reg.topic.lower() or "Explosion" in reg.topic

    assert kb.get_cause_category("TC-99") is None
    assert kb.get_regulation("REG-99") is None


def test_store_precedents_by_type(regulatory_kb_path):
    kb = KnowledgeBase.from_files(regulatory_path=regulatory_kb_path)
    methane = kb.precedents_by_type("methane_explosion")
    assert len(methane) >= 1  # at least Listviazhnaya
    for p in methane:
        assert p.accident_type == "methane_explosion"


def test_store_precedents_by_cause(regulatory_kb_path):
    kb = KnowledgeBase.from_files(regulatory_path=regulatory_kb_path)
    oc01 = kb.precedents_by_cause("OC-01")
    # OC-01 (insufficient production control) is the most common —
    # should appear in many precedents
    assert len(oc01) >= 5


def test_store_summary(regulatory_kb_path, kostenko_kb_path):
    kb = KnowledgeBase.from_files(
        regulatory_path=regulatory_kb_path,
        case_path=kostenko_kb_path,
        case_name="kostenko",
    )
    s = kb.summary()
    assert s["cause_categories"] == 23
    assert s["accident_types"] == 8
    assert s["regulations"] == 14
    assert s["precedents"] == 11
    assert s["case_files"] == ["kostenko"]
    assert s["total_arguments"] == 21


def test_store_strict_mode_rejects_bad_data(regulatory_kb_path, kostenko_with_bad_cause_id):
    """strict=True should raise ValueError on integrity errors."""
    try:
        KnowledgeBase.from_files(
            regulatory_path=regulatory_kb_path,
            case_path=kostenko_with_bad_cause_id,
            case_name="kostenko",
            strict=True,
        )
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "TC-99" in str(e)


def test_store_lenient_mode_allows_bad_data(regulatory_kb_path, kostenko_with_bad_cause_id):
    """strict=False should load even with integrity errors."""
    kb = KnowledgeBase.from_files(
        regulatory_path=regulatory_kb_path,
        case_path=kostenko_with_bad_cause_id,
        case_name="kostenko",
        strict=False,
    )
    errors = kb.check_integrity()
    assert len(errors) == 1
