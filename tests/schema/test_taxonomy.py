"""Tests for taxonomy schema — validates against real KB data."""
import json
from pathlib import Path

from schema.taxonomy import CauseCategory, CauseTier, AccidentType, Regulation

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KB_PATH = PROJECT_ROOT / "data" / "knowledge_base" / "rostechnadzor_regulatory_kb_v2.json"


def test_cause_category_technical():
    cat = CauseCategory(
        id="TC-01",
        label="methane_accumulation",
        description="Elevated methane concentration in the working or goaf",
        details={"typical_sources": ["companion seam release", "goaf accumulation"]},
    )
    assert cat.tier == CauseTier.TECHNICAL
    assert cat.details["typical_sources"][0] == "companion seam release"


def test_cause_category_organizational():
    cat = CauseCategory(
        id="OC-04",
        label="data_falsification",
        description="Falsification of atmospheric monitoring data",
    )
    assert cat.tier == CauseTier.ORGANIZATIONAL
    assert cat.details is None


def test_cause_category_bad_id():
    try:
        CauseCategory(id="XX-01", label="bad", description="bad")
        assert False, "Should have raised validation error"
    except Exception:
        pass


def test_accident_type():
    at = AccidentType(
        id="ATD-01",
        label="methane_explosion",
        russian_term="vzryv metanovozhdushnoy smesi",
        description="Detonation or deflagration of methane-air mixture in underground workings.",
        key_indicators=["pressure_wave", "seismic_event", "sensor_signal_loss"],
        common_precursors=["methane_accumulation_in_goaf", "ignition_source_present"],
    )
    assert at.label == "methane_explosion"
    assert len(at.key_indicators) == 3


def test_regulation():
    reg = Regulation(
        id="REG-01",
        topic="Methane monitoring limits and automatic cutoff",
        requirement="Continuous monitoring of CH4 via stationary sensors. Max 1.0% in outgoing stream.",
        applicable_standard="PB v UK",
        applies_to_accident_types=["methane_explosion", "underground_gas_fire"],
        relevant_cause_categories=["TC-01", "TC-11"],
    )
    assert len(reg.relevant_cause_categories) == 2


def test_regulation_bad_cause_id():
    try:
        Regulation(
            id="REG-01",
            topic="test",
            requirement="test",
            relevant_cause_categories=["TC-01", "INVALID"],
        )
        assert False, "Should have raised validation error"
    except Exception:
        pass


def test_load_all_cause_categories_from_kb():
    """Load every cause category from the real KB and validate."""
    with open(KB_PATH) as f:
        kb = json.load(f)

    taxonomy = kb["domain_knowledge"]["cause_taxonomy"]
    count = 0
    for tier_key in ["technical_cause_categories", "organizational_cause_categories"]:
        for entry in taxonomy[tier_key]:
            details = {k: v for k, v in entry.items() if k not in ("id", "label", "description")}
            CauseCategory(
                id=entry["id"],
                label=entry["label"],
                description=entry["description"],
                details=details if details else None,
            )
            count += 1

    print(f"  Loaded {count} cause categories from KB")
    assert count == 23  # 13 technical + 10 organizational


def test_load_all_accident_types_from_kb():
    """Load every accident type from the real KB."""
    with open(KB_PATH) as f:
        kb = json.load(f)

    types_data = kb["domain_knowledge"]["accident_type_definitions"]["types"]
    count = 0
    for entry in types_data:
        AccidentType(**entry)
        count += 1

    print(f"  Loaded {count} accident types from KB")
    assert count == 8


def test_load_all_regulations_from_kb():
    """Load every regulation from the real KB."""
    with open(KB_PATH) as f:
        kb = json.load(f)

    regs_data = kb["domain_knowledge"]["regulatory_requirements"]
    count = 0
    for entry in regs_data:
        Regulation(**entry)
        count += 1

    print(f"  Loaded {count} regulations from KB")
    assert count == 14


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            print(f"FAIL  {t.__name__}: {e}")
