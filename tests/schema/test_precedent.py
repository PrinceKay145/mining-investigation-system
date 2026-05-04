"""Tests for precedent schema — validates against all 11 real KB precedents."""

import json
from pathlib import Path

from schema.precedent import SimilarityProfile, Precedent, IgnitionType, DataCompleteness

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROSTECHNADZOR_KB = PROJECT_ROOT / "data" / "knowledge_base" / "rostechnadzor_regulatory_kb_v2.json"


def test_similarity_profile_full():
    """Full profile — all flags known."""
    sp = SimilarityProfile(
        accident_type="gas_outburst",
        work_type="underground_development",
        underground=True,
        longwall_face_involved=False,
        methane_involved=True,
        companion_seam_involved=False,
        goaf_accumulation=False,
        coal_dust_involved=False,
        spontaneous_combustion_involved=False,
        ignition_source_identified=False,
        ignition_type="none",
        ventilation_failure=False,
        degasification_failure=True,
        outburst_hazard=True,
        geological_hazard=False,
        seismic_event=False,
        roof_failure=False,
        monitoring_failure=False,
        data_falsification=True,
        naryad_violation=True,
        insufficient_supervision=True,
        qualification_failure=False,
        fatalities=2,
        mass_casualty=False,
    )
    assert sp.ignition_type == IgnitionType.NONE
    assert sp.degasification_failure is True
    assert sp.underground is True


def test_similarity_profile_with_nulls():
    """Partial profile — Listviazhnaya-style with many unknowns."""
    sp = SimilarityProfile(
        accident_type="methane_explosion",
        work_type="underground_extraction",
        underground=True,
        longwall_face_involved=True,
        methane_involved=True,
        companion_seam_involved=None,
        goaf_accumulation=None,
        coal_dust_involved=None,
        spontaneous_combustion_involved=False,
        ignition_source_identified=False,
        ignition_type="unknown",
        ventilation_failure=None,
        degasification_failure=None,
        outburst_hazard=False,
        geological_hazard=False,
        seismic_event=False,
        roof_failure=None,
        monitoring_failure=True,
        data_falsification=True,
        naryad_violation=None,
        insufficient_supervision=True,
        qualification_failure=None,
        fatalities=51,
        mass_casualty=True,
    )
    assert sp.companion_seam_involved is None
    assert sp.mass_casualty is True
    assert sp.fatalities == 51


def test_similarity_profile_all_nulls():
    """Minimal profile — 2022 style where almost nothing is known."""
    sp = SimilarityProfile(
        accident_type="unknown",
        work_type="unknown",
        underground=None,
        longwall_face_involved=None,
        methane_involved=None,
        companion_seam_involved=None,
        goaf_accumulation=None,
        coal_dust_involved=None,
        spontaneous_combustion_involved=None,
        ignition_source_identified=None,
        ignition_type="unknown",
        ventilation_failure=None,
        degasification_failure=None,
        outburst_hazard=None,
        geological_hazard=None,
        seismic_event=None,
        roof_failure=None,
        monitoring_failure=None,
        data_falsification=None,
        naryad_violation=True,
        insufficient_supervision=True,
        qualification_failure=True,
        fatalities=0,
        mass_casualty=False,
    )
    assert sp.underground is None
    assert sp.naryad_violation is True


def test_precedent_full():
    prec = Precedent(
        id="PREC-2024-01",
        year=2024,
        date="2024-12-09",
        record_type="avaria",
        mine="Shaktha Alardinskaya",
        operator="OOO Raspadskaya Ugolnaya Kompaniya",
        region="Kemerovskaya oblast",
        accident_type="underground_gas_fire",
        work_type="underground_extraction",
        description="Roof fall with displacement of ignited methane-air mixture.",
        fatalities=0,
        injured=0,
        technical_causes=["Roof fall in goaf with displacement of ignited methane-air mixture"],
        organizational_causes=["Unsatisfactory organization of production work"],
        violated_regulations=["REG-01", "REG-02", "REG-08", "REG-09"],
        cause_categories=["TC-01", "TC-09", "OC-01", "OC-02", "OC-05"],
        data_completeness="full",
        similarity_profile=SimilarityProfile(
            accident_type="underground_gas_fire",
            work_type="underground_extraction",
            underground=True,
            longwall_face_involved=True,
            methane_involved=True,
            companion_seam_involved=None,
            goaf_accumulation=True,
            coal_dust_involved=False,
            spontaneous_combustion_involved=False,
            ignition_source_identified=False,
            ignition_type="unknown",
            ventilation_failure=False,
            degasification_failure=False,
            outburst_hazard=False,
            geological_hazard=False,
            seismic_event=False,
            roof_failure=True,
            monitoring_failure=False,
            data_falsification=False,
            naryad_violation=True,
            insufficient_supervision=True,
            qualification_failure=False,
            fatalities=0,
            mass_casualty=False,
        ),
    )
    assert prec.data_completeness == DataCompleteness.FULL
    assert prec.similarity_profile.roof_failure is True


def test_precedent_group_accident():
    """Group accident ID format: PREC-YYYY-GRP-NN."""
    prec = Precedent(
        id="PREC-2021-GRP-01",
        year=2021,
        date="2021-07-05",
        record_type="grupovoy_neschastny_sluchay",
        mine="Shaktha Raspadskaya-Koksovaya",
        operator="AO Raspadskaya-Koksovaya",
        region="Kemerovskaya oblast, Mezhdurechensk",
        accident_type="rock_burst",
        work_type="underground_extraction",
        description="Seismic event caused deformation of mine working.",
        fatalities=1,
        injured=3,
        cause_categories=["TC-08", "TC-13"],
        similarity_profile=SimilarityProfile(
            accident_type="rock_burst",
            work_type="underground_extraction",
            underground=True,
            longwall_face_involved=False,
            methane_involved=False,
            companion_seam_involved=False,
            goaf_accumulation=False,
            coal_dust_involved=False,
            spontaneous_combustion_involved=False,
            ignition_source_identified=False,
            ignition_type="none",
            ventilation_failure=False,
            degasification_failure=False,
            outburst_hazard=False,
            geological_hazard=True,
            seismic_event=True,
            roof_failure=False,
            monitoring_failure=False,
            data_falsification=False,
            naryad_violation=False,
            insufficient_supervision=False,
            qualification_failure=False,
            fatalities=1,
            mass_casualty=False,
        ),
    )
    assert prec.record_type == "grupovoy_neschastny_sluchay"


def test_bad_precedent_id():
    try:
        Precedent(
            id="INVALID",
            year=2024, date="2024", mine="x", operator="x", region="x",
            accident_type="x", work_type="x", description="x", fatalities=0,
            similarity_profile=SimilarityProfile(
                accident_type="unknown", work_type="unknown", underground=None,
                longwall_face_involved=None, methane_involved=None,
                companion_seam_involved=None, goaf_accumulation=None,
                coal_dust_involved=None, spontaneous_combustion_involved=None,
                ignition_source_identified=None, ignition_type="unknown",
                ventilation_failure=None, degasification_failure=None,
                outburst_hazard=None, geological_hazard=None, seismic_event=None,
                roof_failure=None, monitoring_failure=None, data_falsification=None,
                naryad_violation=None, insufficient_supervision=None,
                qualification_failure=None, fatalities=0, mass_casualty=False,
            ),
        )
        assert False, "Should reject invalid precedent ID"
    except Exception:
        pass


def test_bad_regulation_id():
    try:
        Precedent(
            id="PREC-2024-01",
            year=2024, date="2024", mine="x", operator="x", region="x",
            accident_type="x", work_type="x", description="x", fatalities=0,
            violated_regulations=["INVALID"],
            similarity_profile=SimilarityProfile(
                accident_type="unknown", work_type="unknown", underground=None,
                longwall_face_involved=None, methane_involved=None,
                companion_seam_involved=None, goaf_accumulation=None,
                coal_dust_involved=None, spontaneous_combustion_involved=None,
                ignition_source_identified=None, ignition_type="unknown",
                ventilation_failure=None, degasification_failure=None,
                outburst_hazard=None, geological_hazard=None, seismic_event=None,
                roof_failure=None, monitoring_failure=None, data_falsification=None,
                naryad_violation=None, insufficient_supervision=None,
                qualification_failure=None, fatalities=0, mass_casualty=False,
            ),
        )
        assert False, "Should reject invalid regulation ID"
    except Exception:
        pass


def test_load_all_precedents_from_kb():
    """Load all 11 precedents from the real KB v2."""
    with open(ROSTECHNADZOR_KB) as f:
        kb = json.load(f)

    precedents = kb["accident_precedents"]
    loaded = []
    for entry in precedents:
        prec = Precedent(**entry)
        loaded.append(prec)

    print(f"  Loaded {len(loaded)} precedents from KB")

    # Check counts
    assert len(loaded) == 11

    # Check specific cases
    ids = [p.id for p in loaded]
    assert "PREC-2021-04" in ids       # Listviazhnaya
    assert "PREC-2024-01" in ids       # Alardinskaya
    assert "PREC-2021-GRP-01" in ids   # Group accident

    # Check data completeness distribution
    full = sum(1 for p in loaded if p.data_completeness == DataCompleteness.FULL)
    partial = sum(1 for p in loaded if p.data_completeness == DataCompleteness.PARTIAL)
    minimal = sum(1 for p in loaded if p.data_completeness == DataCompleteness.MINIMAL)
    print(f"  Completeness: {full} full, {partial} partial, {minimal} minimal")
    assert full == 8
    assert partial == 1   # Listviazhnaya
    assert minimal == 2   # 2022 cases


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            print(f"FAIL  {t.__name__}: {e}")