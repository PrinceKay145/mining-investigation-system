"""Tests for v2 identification — accident type classification."""

from kb.loader import load_regulatory_kb, load_case_file
from schema.argument import Argument
from v2_identification import classify, build_cause_to_type_index


# ---------------------------------------------------------------------------
# build_cause_to_type_index
# ---------------------------------------------------------------------------

def test_index_maps_methane_causes(regulatory_kb_path):
    """Methane-related causes should map to methane_explosion."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    index = build_cause_to_type_index(reg_kb.regulations)
    assert "TC-01" in index
    assert "methane_explosion" in index["TC-01"]


def test_index_excludes_type_agnostic_regulations(regulatory_kb_path):
    """Causes only mentioned by 'all'-type regulations must not appear in index."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    index = build_cause_to_type_index(reg_kb.regulations)
    # OC-01 is only in REG-09 (applies_to: ["all"]), so it should be absent
    assert "OC-01" not in index


def test_index_handles_multiple_types_per_cause(regulatory_kb_path):
    """A cause covered by regulations targeting multiple types maps to all of them."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    index = build_cause_to_type_index(reg_kb.regulations)
    # TC-04 (chemical ignition) appears in REG-05 (methane/gas-fire) and REG-14 (surface_fire)
    assert "TC-04" in index
    assert "surface_fire" in index["TC-04"]
    assert "methane_explosion" in index["TC-04"]


# ---------------------------------------------------------------------------
# classify — Kostenko ground truth
# ---------------------------------------------------------------------------

def test_kostenko_classified_as_methane_explosion(regulatory_kb_path, kostenko_kb_path):
    """The 21 Kostenko arguments should classify as methane_explosion."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    result = classify(case.arguments, reg_kb.regulations)
    assert result.primary_type == "methane_explosion"


def test_kostenko_secondary_includes_underground_gas_fire(regulatory_kb_path, kostenko_kb_path):
    """Kostenko's initial event was a fire that escalated — both types should rank."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    result = classify(case.arguments, reg_kb.regulations)
    assert "underground_gas_fire" in result.secondary_types


def test_kostenko_cause_profile_counts(regulatory_kb_path, kostenko_kb_path):
    """The cause_profile must reflect the actual tag frequencies in the KB."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    result = classify(case.arguments, reg_kb.regulations)
    # From the backfill: TC-01 ×7, TC-02 ×5, TC-04 ×3
    assert result.cause_profile["TC-01"] == 7
    assert result.cause_profile["TC-02"] == 5
    assert result.cause_profile["TC-04"] == 3


def test_kostenko_all_cause_categories_property(regulatory_kb_path, kostenko_kb_path):
    """The all_cause_categories property exposes the v3-Jaccard input set."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    result = classify(case.arguments, reg_kb.regulations)
    cats = result.all_cause_categories
    assert "TC-01" in cats
    assert "TC-10" in cats  # coal dust
    assert isinstance(cats, set)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_classify_empty_arguments(regulatory_kb_path):
    """No arguments → primary_type='unknown' and empty profile."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    result = classify([], reg_kb.regulations)
    assert result.primary_type == "unknown"
    assert result.secondary_types == []
    assert result.cause_profile == {}
    assert result.type_votes == {}


def test_classify_arguments_with_only_oc01(regulatory_kb_path):
    """Args tagged only with OC-01 (only in 'all'-type reg) get no type votes."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    arg = Argument(
        id="X-A1", source="X", topic="organizational",
        claim="Production control was insufficient",
        evidence="Internal audit findings",
        warrant="OC-01 manifestation",
        confidence=0.7,
        cause_categories=["OC-01"],
    )
    result = classify([arg], reg_kb.regulations)
    assert result.primary_type == "unknown"
    assert result.cause_profile == {"OC-01": 1}
    assert result.type_votes == {}


def test_classify_secondary_threshold_strictness(regulatory_kb_path, kostenko_kb_path):
    """A higher threshold should drop more types from secondary."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    permissive = classify(case.arguments, reg_kb.regulations, secondary_threshold=0.1)
    strict = classify(case.arguments, reg_kb.regulations, secondary_threshold=0.95)
    assert len(strict.secondary_types) <= len(permissive.secondary_types)
