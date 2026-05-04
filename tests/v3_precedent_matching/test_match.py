"""Tests for v3 precedent matching — two-step CBR."""

from kb.loader import load_regulatory_kb, load_case_file
from schema.classification import ClassificationResult
from schema.precedent import Precedent, SimilarityProfile, IgnitionType, DataCompleteness
from v2_identification import classify
from v3_precedent_matching import match_precedents


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_profile(accident_type: str) -> SimilarityProfile:
    """Profile with all bool flags set to None ('unknown') — for synthetic Precedents
    where v3 testing only needs accident_type + cause_categories."""
    return SimilarityProfile(
        accident_type=accident_type,
        work_type="underground_extraction",
        underground=None,
        longwall_face_involved=None,
        methane_involved=None,
        companion_seam_involved=None,
        goaf_accumulation=None,
        coal_dust_involved=None,
        spontaneous_combustion_involved=None,
        ignition_source_identified=None,
        ignition_type=IgnitionType.UNKNOWN,
        ventilation_failure=None,
        degasification_failure=None,
        outburst_hazard=None,
        geological_hazard=None,
        seismic_event=None,
        roof_failure=None,
        monitoring_failure=None,
        data_falsification=None,
        naryad_violation=None,
        insufficient_supervision=None,
        qualification_failure=None,
        fatalities=0,
        mass_casualty=False,
    )


def _synthetic_precedent(
    pid: str,
    accident_type: str,
    cause_categories: list[str],
) -> Precedent:
    """Minimal valid Precedent for unit tests."""
    return Precedent(
        id=pid,
        year=2020,
        date="2020-01-01",
        record_type="avaria",
        mine="test",
        operator="test",
        region="test",
        accident_type=accident_type,
        work_type="underground_extraction",
        description="synthetic",
        fatalities=0,
        cause_categories=cause_categories,
        violated_regulations=[],
        data_completeness=DataCompleteness.FULL,
        similarity_profile=_synthetic_profile(accident_type),
    )


# ---------------------------------------------------------------------------
# Type filter
# ---------------------------------------------------------------------------

def test_type_filter_keeps_primary_matches():
    """Precedents with accident_type == primary_type pass the type filter."""
    classif = ClassificationResult(
        primary_type="methane_explosion",
        secondary_types=[],
        cause_profile={"TC-01": 5},
    )
    precs = [
        _synthetic_precedent("PREC-9999-01", "methane_explosion", ["TC-01"]),
        _synthetic_precedent("PREC-9999-02", "rock_burst", ["TC-08"]),
    ]
    result = match_precedents(classif, precs)
    assert result.filtered_count == 1
    assert len(result.matches) == 1
    assert result.matches[0].precedent_id == "PREC-9999-01"
    assert result.matches[0].matched_via == "primary"


def test_type_filter_includes_secondary_matches():
    """Precedents matching a secondary_type are included with matched_via='secondary'."""
    classif = ClassificationResult(
        primary_type="methane_explosion",
        secondary_types=["underground_gas_fire"],
        cause_profile={"TC-01": 5},
    )
    precs = [
        _synthetic_precedent("PREC-9999-03", "methane_explosion", ["TC-01"]),
        _synthetic_precedent("PREC-9999-04", "underground_gas_fire", ["TC-01"]),
        _synthetic_precedent("PREC-9999-05", "slope_failure", ["TC-13"]),
    ]
    result = match_precedents(classif, precs)
    assert result.filtered_count == 2
    via_map = {m.precedent_id: m.matched_via for m in result.matches}
    assert via_map["PREC-9999-03"] == "primary"
    assert via_map["PREC-9999-04"] == "secondary"
    assert "PREC-9999-05" not in via_map


# ---------------------------------------------------------------------------
# Jaccard scoring
# ---------------------------------------------------------------------------

def test_jaccard_perfect_match():
    """Identical cause sets → score 1.0."""
    classif = ClassificationResult(
        primary_type="methane_explosion",
        cause_profile={"TC-01": 1, "TC-02": 1},
    )
    precs = [_synthetic_precedent("PREC-9999-06", "methane_explosion", ["TC-01", "TC-02"])]
    result = match_precedents(classif, precs)
    assert result.matches[0].overlap_score == 1.0
    assert result.matches[0].shared_cause_categories == ["TC-01", "TC-02"]


def test_jaccard_zero_overlap():
    """Disjoint cause sets → score 0.0."""
    classif = ClassificationResult(
        primary_type="methane_explosion",
        cause_profile={"TC-01": 1, "TC-02": 1},
    )
    precs = [_synthetic_precedent("PREC-9999-06", "methane_explosion", ["OC-01", "OC-02"])]
    result = match_precedents(classif, precs)
    assert result.matches[0].overlap_score == 0.0
    assert result.matches[0].shared_cause_categories == []


def test_jaccard_partial_overlap():
    """Half overlap: 1 shared / 3 union = 1/3."""
    classif = ClassificationResult(
        primary_type="methane_explosion",
        cause_profile={"TC-01": 1, "TC-02": 1},
    )
    precs = [_synthetic_precedent("PREC-9999-06", "methane_explosion", ["TC-01", "OC-01"])]
    result = match_precedents(classif, precs)
    assert abs(result.matches[0].overlap_score - 1 / 3) < 1e-9
    assert result.matches[0].shared_cause_categories == ["TC-01"]


# ---------------------------------------------------------------------------
# Sorting and threshold
# ---------------------------------------------------------------------------

def test_matches_sorted_descending():
    """Matches must be returned in descending overlap order."""
    classif = ClassificationResult(
        primary_type="methane_explosion",
        cause_profile={"TC-01": 1, "TC-02": 1, "TC-03": 1},
    )
    precs = [
        _synthetic_precedent("PREC-9999-07",  "methane_explosion", ["TC-01"]),
        _synthetic_precedent("PREC-9999-09", "methane_explosion", ["TC-01", "TC-02", "TC-03"]),
        _synthetic_precedent("PREC-9999-08",  "methane_explosion", ["TC-01", "TC-02"]),
    ]
    result = match_precedents(classif, precs)
    ids = [m.precedent_id for m in result.matches]
    assert ids == ["PREC-9999-09", "PREC-9999-08", "PREC-9999-07"]


def test_threshold_filters_low_overlap():
    """threshold=0.5 should drop matches whose Jaccard < 0.5."""
    classif = ClassificationResult(
        primary_type="methane_explosion",
        cause_profile={"TC-01": 1, "TC-02": 1, "TC-03": 1},
    )
    precs = [
        _synthetic_precedent("PREC-9999-01", "methane_explosion", ["TC-01"]),                    # 1/3 ≈ 0.33
        _synthetic_precedent("PREC-9999-02", "methane_explosion", ["TC-01", "TC-02", "TC-03"]),  # 1.0
    ]
    result = match_precedents(classif, precs, threshold=0.5)
    ids = [m.precedent_id for m in result.matches]
    assert ids == ["PREC-9999-02"]
    # Funnel: filtered_count is pre-threshold (after type filter only)
    assert result.filtered_count == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_no_precedents_match_type():
    """If no precedents match v2's types, the result is empty but well-formed."""
    classif = ClassificationResult(
        primary_type="methane_explosion",
        cause_profile={"TC-01": 1},
    )
    precs = [_synthetic_precedent("PREC-9999-06", "slope_failure", ["TC-13"])]
    result = match_precedents(classif, precs)
    assert result.matches == []
    assert result.filtered_count == 0
    assert result.total_precedents == 1


def test_funnel_telemetry():
    """total_precedents and filtered_count must be reported accurately."""
    classif = ClassificationResult(
        primary_type="methane_explosion",
        cause_profile={"TC-01": 1},
    )
    precs = [
        _synthetic_precedent("PREC-9999-11", "methane_explosion", ["TC-01"]),
        _synthetic_precedent("PREC-9999-12", "methane_explosion", ["TC-02"]),
        _synthetic_precedent("PREC-9999-13", "rock_burst", ["TC-08"]),
        _synthetic_precedent("PREC-9999-14", "slope_failure", ["TC-13"]),
    ]
    result = match_precedents(classif, precs)
    assert result.total_precedents == 4
    assert result.filtered_count == 2  # the two methane_explosion ones


# ---------------------------------------------------------------------------
# Real Kostenko data
# ---------------------------------------------------------------------------

def test_kostenko_top_match_is_listviazhnaya(regulatory_kb_path, kostenko_kb_path):
    """End-to-end: Kostenko's top precedent match should be Listviazhnaya."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    classif = classify(case.arguments, reg_kb.regulations)

    result = match_precedents(classif, reg_kb.precedents)
    assert result.matches, "Should find at least one match"
    assert result.matches[0].precedent_id == "PREC-2021-04"  # Listviazhnaya
    assert result.matches[0].matched_via == "primary"


def test_kostenko_match_funnel(regulatory_kb_path, kostenko_kb_path):
    """11 precedents in KB → 2 pass type filter (Listviazhnaya + Alardinskaya)."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    classif = classify(case.arguments, reg_kb.regulations)

    result = match_precedents(classif, reg_kb.precedents)
    assert result.total_precedents == 11
    assert result.filtered_count == 2
    ids = {m.precedent_id for m in result.matches}
    assert ids == {"PREC-2021-04", "PREC-2024-01"}


def test_kostenko_overlap_includes_tc01(regulatory_kb_path, kostenko_kb_path):
    """Both Kostenko matches share at least TC-01 (methane accumulation)."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    classif = classify(case.arguments, reg_kb.regulations)

    result = match_precedents(classif, reg_kb.precedents)
    for m in result.matches:
        assert "TC-01" in m.shared_cause_categories
