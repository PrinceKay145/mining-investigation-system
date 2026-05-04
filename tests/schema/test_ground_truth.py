"""Tests for ground_truth schema — validates against real Kostenko KB."""

import json
from pathlib import Path

from schema.ground_truth import (
    AttackRelation, AttackType,
    SupportRelation, SupportStrength,
    OpenQuestion,
    GroundTruth,
    CaseMetadata, CaseFile,
)
from schema.argument import Argument

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KOSTENKO_KB = PROJECT_ROOT / "data" / "knowledge_base" / "kostenko_knowledge_base.json"


# ---------------------------------------------------------------------------
# AttackRelation
# ---------------------------------------------------------------------------

def test_attack_rebutting():
    atk = AttackRelation(
        id="ATK-1",
        attacker="U-A3",
        target="D-A5",
        type="rebutting",
        description="Specific vs unknown ignition source — mutually incompatible.",
    )
    assert atk.type == AttackType.REBUTTING


def test_attack_undercutting():
    atk = AttackRelation(
        id="ATK-4",
        attacker="K-A7",
        target="D-A8",
        type="undercutting",
        description="Divergent explosion locations undermine each other's reconstruction.",
    )
    assert atk.type == AttackType.UNDERCUTTING


def test_attack_bad_id():
    try:
        AttackRelation(id="INVALID", attacker="A", target="B",
                       type="rebutting", description="x")
        assert False, "Should reject invalid attack ID"
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SupportRelation
# ---------------------------------------------------------------------------

def test_support_unanimous():
    sup = SupportRelation(
        id="SUP-1",
        supporters=["U-A2", "K-A3", "D-A4"],
        topic="Spontaneous combustion excluded",
        description="All three experts exclude spontaneous combustion.",
        strength="unanimous",
    )
    assert sup.strength == SupportStrength.UNANIMOUS
    assert len(sup.supporters) == 3


def test_support_bilateral():
    sup = SupportRelation(
        id="SUP-4",
        supporters=["K-A2", "D-A1"],
        topic="K2 seam was the primary methane source",
        description="Both identify K2 as methane source.",
        strength="bilateral",
    )
    assert sup.strength == SupportStrength.BILATERAL
    assert len(sup.supporters) == 2


def test_support_needs_at_least_two():
    try:
        SupportRelation(
            id="SUP-99",
            supporters=["U-A1"],  # only one — invalid
            topic="test",
            description="test",
            strength="bilateral",
        )
        assert False, "Should reject single supporter"
    except Exception:
        pass


# ---------------------------------------------------------------------------
# OpenQuestion
# ---------------------------------------------------------------------------

def test_open_question():
    oq = OpenQuestion(
        id="OQ-1",
        question="Was the shearer operating at the time of ignition?",
        relevance="Would affect probability of mechanical sparking.",
        raised_by=["D"],
    )
    assert oq.raised_by == ["D"]


def test_open_question_multiple_raisers():
    oq = OpenQuestion(
        id="OQ-3",
        question="What was the actual CH4 distribution in the goaf?",
        relevance="Critical for resolving explosion location dispute.",
        raised_by=["D", "K"],
    )
    assert len(oq.raised_by) == 2


# ---------------------------------------------------------------------------
# GroundTruth
# ---------------------------------------------------------------------------

def test_ground_truth_empty():
    """A case with no annotations yet (e.g. UBB before we annotate it)."""
    gt = GroundTruth()
    assert gt.attack_relations == []
    assert gt.support_relations == []
    assert gt.open_questions == []


# ---------------------------------------------------------------------------
# CaseFile
# ---------------------------------------------------------------------------

def _make_test_argument(**overrides) -> Argument:
    """Helper to build a minimal valid Argument."""
    defaults = dict(
        id="X-A1", source="X", topic="test", claim="test claim",
        evidence="test evidence", warrant="test warrant",
        confidence=0.5, cause_categories=["TC-01"],
    )
    defaults.update(overrides)
    return Argument(**defaults)


def test_casefile_minimal():
    cf = CaseFile(
        metadata=CaseMetadata(
            case="Test Case", date="2024-01-01", location="Test Mine",
        ),
        arguments=[_make_test_argument()],
        ground_truth=GroundTruth(),
    )
    assert len(cf.arguments) == 1
    assert cf.ground_truth.attack_relations == []


def test_casefile_with_ground_truth():
    cf = CaseFile(
        metadata=CaseMetadata(
            case="Test", date="2024", location="Test",
        ),
        arguments=[
            _make_test_argument(id="A-1", topic="Ignition"),
            _make_test_argument(id="B-1", topic="Ignition"),
        ],
        ground_truth=GroundTruth(
            attack_relations=[
                AttackRelation(
                    id="ATK-1", attacker="A-1", target="B-1",
                    type="rebutting", description="Contradictory ignition claims.",
                ),
            ],
            support_relations=[],
            open_questions=[],
        ),
    )
    assert len(cf.ground_truth.attack_relations) == 1


# ---------------------------------------------------------------------------
# Integration: load full Kostenko KB
# ---------------------------------------------------------------------------

def test_load_kostenko_casefile():
    """Load the full Kostenko KB (with permanent cause_categories) as a CaseFile."""
    with open(KOSTENKO_KB) as f:
        kb = json.load(f)

    # cause_categories are permanent in the file as of the 2026-04-27 backfill —
    # construct Arguments directly from raw data
    arguments = [Argument(**raw_arg) for raw_arg in kb["arguments"]]

    # Build ground truth from argumentation_framework
    af = kb["argumentation_framework"]

    attacks = [AttackRelation(**a) for a in af["attack_relations"]]
    supports = [SupportRelation(**s) for s in af["support_relations"]]
    open_qs = [OpenQuestion(**q) for q in af["open_questions"]]

    ground_truth = GroundTruth(
        attack_relations=attacks,
        support_relations=supports,
        open_questions=open_qs,
    )

    # Build metadata
    meta_raw = kb["metadata"]
    metadata = CaseMetadata(
        case=meta_raw["case"],
        date=meta_raw["date"],
        location=meta_raw["location"],
        sources=meta_raw["sources"],
        investigation_questions=meta_raw["investigation_questions"],
        extra={"longwall": meta_raw.get("longwall")},
    )

    # Assemble CaseFile
    case_file = CaseFile(
        metadata=metadata,
        arguments=arguments,
        ground_truth=ground_truth,
    )

    # Assertions
    print(f"  Arguments: {len(case_file.arguments)}")
    print(f"  Attacks:   {len(case_file.ground_truth.attack_relations)}")
    print(f"  Supports:  {len(case_file.ground_truth.support_relations)}")
    print(f"  Open Qs:   {len(case_file.ground_truth.open_questions)}")

    assert len(case_file.arguments) == 21
    assert len(case_file.ground_truth.attack_relations) == 4
    assert len(case_file.ground_truth.support_relations) == 5
    assert len(case_file.ground_truth.open_questions) == 5

    # Verify attack IDs reference real argument IDs
    arg_ids = {a.id for a in case_file.arguments}
    for atk in case_file.ground_truth.attack_relations:
        assert atk.attacker in arg_ids, f"ATK {atk.id}: attacker '{atk.attacker}' not in arguments"
        assert atk.target in arg_ids, f"ATK {atk.id}: target '{atk.target}' not in arguments"

    # Verify support IDs reference real argument IDs
    for sup in case_file.ground_truth.support_relations:
        for sid in sup.supporters:
            assert sid in arg_ids, f"SUP {sup.id}: supporter '{sid}' not in arguments"


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            print(f"FAIL  {t.__name__}: {e}")