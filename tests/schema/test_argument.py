"""Tests for argument schema."""

from pathlib import Path

from schema.argument import Argument

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KOSTENKO_KB = PROJECT_ROOT / "data" / "knowledge_base" / "kostenko_knowledge_base.json"


def test_valid_expert_argument():
    arg = Argument(
        id="U-A1",
        source="U",
        topic="Ignition location",
        claim="Initial ignition occurred in the upper part of longwall 48K3-Z, sections 142-145.",
        evidence="Angle grinder with 6 used disks found in conveyor drift; aerosol can on shearer.",
        warrant="Physical items capable of producing ignition are concentrated at that location.",
        confidence=0.75,
        cause_categories=["TC-02"],
    )
    assert arg.id == "U-A1"
    assert arg.confidence == 0.75
    assert arg.cause_categories == ["TC-02"]


def test_valid_agent_argument():
    arg = Argument(
        id="agent_1_001",
        source="agent_1",
        topic="Methane source",
        claim="K2 companion seam was the primary methane source.",
        evidence="Post-accident methane survey: 17.9% CH4 at section 140 floor level.",
        warrant="K2 seam 3.35m below K3; abutment pressure creates decompression zone.",
        confidence=0.85,
        cause_categories=["TC-01", "TC-07"],
    )
    assert len(arg.cause_categories) == 2


def test_multiple_cause_categories():
    """Arguments often span both technical and organizational causes."""
    arg = Argument(
        id="K-A4",
        source="K",
        topic="Ignition source",
        claim="AFC conveyor chain sparking was the most probable ignition cause.",
        evidence="Witness testimony of sparking; physical tests confirmed sparking possible.",
        warrant="Sparking zone overlaps with sub-conveyor methane accumulation zone.",
        confidence=0.72,
        cause_categories=["TC-02", "OC-01"],
    )
    assert "TC-02" in arg.cause_categories
    assert "OC-01" in arg.cause_categories


def test_empty_cause_categories_rejected():
    try:
        Argument(
            id="X-A1",
            source="X",
            topic="test",
            claim="test",
            evidence="test",
            warrant="test",
            confidence=0.5,
            cause_categories=[],
        )
        assert False, "Should reject empty cause_categories"
    except Exception:
        pass


def test_missing_cause_categories_rejected():
    try:
        Argument(
            id="X-A1",
            source="X",
            topic="test",
            claim="test",
            evidence="test",
            warrant="test",
            confidence=0.5,
            # cause_categories omitted entirely
        )
        assert False, "Should reject missing cause_categories"
    except Exception:
        pass


def test_invalid_cause_id_rejected():
    try:
        Argument(
            id="X-A1",
            source="X",
            topic="test",
            claim="test",
            evidence="test",
            warrant="test",
            confidence=0.5,
            cause_categories=["TC-01", "INVALID"],
        )
        assert False, "Should reject invalid cause category ID"
    except Exception:
        pass


def test_confidence_bounds():
    """Confidence must be 0.0–1.0."""
    try:
        Argument(
            id="X-A1", source="X", topic="t", claim="t",
            evidence="t", warrant="t", confidence=1.5,
            cause_categories=["TC-01"],
        )
        assert False, "Should reject confidence > 1.0"
    except Exception:
        pass

    try:
        Argument(
            id="X-A1", source="X", topic="t", claim="t",
            evidence="t", warrant="t", confidence=-0.1,
            cause_categories=["TC-01"],
        )
        assert False, "Should reject confidence < 0.0"
    except Exception:
        pass


def test_empty_strings_rejected():
    """No empty-string fields allowed for required text fields."""
    try:
        Argument(
            id="X-A1", source="X", topic="", claim="t",
            evidence="t", warrant="t", confidence=0.5,
            cause_categories=["TC-01"],
        )
        assert False, "Should reject empty topic"
    except Exception:
        pass


def test_kostenko_first_argument_loads():
    """First Kostenko argument loads cleanly from real KB data."""
    import json
    with open(KOSTENKO_KB) as f:
        kb = json.load(f)

    raw = kb["arguments"][0]  # U-A1
    arg = Argument(**raw)
    assert arg.id == "U-A1"
    assert arg.cause_categories  # backfilled, must be non-empty


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            print(f"FAIL  {t.__name__}: {e}")