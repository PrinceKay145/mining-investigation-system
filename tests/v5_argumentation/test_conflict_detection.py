"""
Tests for v5 conflict detection — topic filter + mocked LLM confirmation.

The LLM is replaced with a fake that returns scripted responses keyed by
the pair of argument IDs in the prompt. This lets us verify the filter
logic, parallelization correctness, and AttackRelation/SupportRelation
assembly without touching a real model.
"""

from llm.client import CompletionResult
from llm.logging import RunContext
from schema.argument import Argument
from schema.ground_truth import AttackType, SupportStrength
from v5_argumentation.conflict_detection import (
    ConflictDetectionResponse,
    detect_conflicts,
    topic_filter,
)


def _arg(arg_id: str, topic: str, source: str = "X",
         confidence: float = 0.5) -> Argument:
    return Argument(
        id=arg_id, source=source, topic=topic,
        claim=f"claim of {arg_id}", evidence="e", warrant="w",
        confidence=confidence, cause_categories=["TC-01"],
    )


# ---------------------------------------------------------------------------
# Fake LLM client
# ---------------------------------------------------------------------------

class FakeClient:
    """
    Returns scripted ConflictDetectionResponse-shaped JSON keyed by which
    two argument IDs appear in the rendered prompt.
    """

    def __init__(self, responses: dict[frozenset[str], str]):
        # responses: {frozenset({id_a, id_b}): json_string}
        self.responses = responses
        self.calls: list[frozenset[str]] = []

    def complete_json(self, prompt: str, schema, system=None,
                      max_tokens=None, temperature: float = 0.0):
        # Identify the pair from substrings in the prompt
        ids_in_prompt = [
            line.split("**ID:**", 1)[1].strip()
            for line in prompt.split("\n")
            if "**ID:**" in line
        ]
        key = frozenset(ids_in_prompt)
        self.calls.append(key)
        return schema.model_validate_json(self.responses[key])

    def complete(self, *args, **kwargs) -> CompletionResult:
        raise AssertionError("v5 conflict detection should not call complete(); use complete_json")


def _resp(relation: str, rationale: str = "test") -> str:
    import json
    return json.dumps({"relation": relation, "rationale": rationale})


# ---------------------------------------------------------------------------
# topic_filter
# ---------------------------------------------------------------------------

def test_topic_filter_returns_same_topic_pairs():
    args = [
        _arg("A1", "Ignition source"),
        _arg("A2", "Ignition source"),
        _arg("A3", "Methane source"),
    ]
    pairs = topic_filter(args)
    assert len(pairs) == 1
    a, b = pairs[0]
    assert {a.id, b.id} == {"A1", "A2"}


def test_topic_filter_handles_multiple_pairs_per_topic():
    args = [
        _arg("A1", "X"),
        _arg("A2", "X"),
        _arg("A3", "X"),
    ]
    # 3 args same topic → 3 pairs (3 choose 2)
    pairs = topic_filter(args)
    assert len(pairs) == 3


def test_topic_filter_no_match():
    args = [
        _arg("A1", "X"),
        _arg("A2", "Y"),
        _arg("A3", "Z"),
    ]
    assert topic_filter(args) == []


def test_topic_filter_preserves_order():
    """A precedes B by index in the original list — needed for directional undercutting."""
    args = [_arg("A1", "X"), _arg("A2", "X"), _arg("A3", "X")]
    pairs = topic_filter(args)
    for a, b in pairs:
        assert args.index(a) < args.index(b)


# ---------------------------------------------------------------------------
# detect_conflicts — relation assembly
# ---------------------------------------------------------------------------

def test_rebutting_produces_two_directed_attacks(tmp_path):
    args = [_arg("A1", "X"), _arg("A2", "X")]
    client = FakeClient({frozenset({"A1", "A2"}): _resp("rebutting", "incompatible")})
    run = RunContext(name="test", base_dir=tmp_path)
    attacks, supports = detect_conflicts(args, client, run)
    assert len(attacks) == 2
    assert {(a.attacker, a.target) for a in attacks} == {("A1", "A2"), ("A2", "A1")}
    assert all(a.type == AttackType.REBUTTING for a in attacks)
    assert supports == []


def test_undercutting_a_to_b_produces_one_directed_attack(tmp_path):
    args = [_arg("A1", "X"), _arg("A2", "X")]
    client = FakeClient({frozenset({"A1", "A2"}): _resp("undercutting_a_to_b")})
    run = RunContext(name="test", base_dir=tmp_path)
    attacks, supports = detect_conflicts(args, client, run)
    assert len(attacks) == 1
    assert attacks[0].attacker == "A1"
    assert attacks[0].target == "A2"
    assert attacks[0].type == AttackType.UNDERCUTTING


def test_undercutting_b_to_a_reverses_direction(tmp_path):
    args = [_arg("A1", "X"), _arg("A2", "X")]
    client = FakeClient({frozenset({"A1", "A2"}): _resp("undercutting_b_to_a")})
    run = RunContext(name="test", base_dir=tmp_path)
    attacks, supports = detect_conflicts(args, client, run)
    assert len(attacks) == 1
    assert attacks[0].attacker == "A2"
    assert attacks[0].target == "A1"


def test_support_produces_support_relation(tmp_path):
    args = [_arg("A1", "X"), _arg("A2", "X")]
    client = FakeClient({frozenset({"A1", "A2"}): _resp("support", "reinforcing")})
    run = RunContext(name="test", base_dir=tmp_path)
    attacks, supports = detect_conflicts(args, client, run)
    assert attacks == []
    assert len(supports) == 1
    assert set(supports[0].supporters) == {"A1", "A2"}
    assert supports[0].strength == SupportStrength.BILATERAL
    assert supports[0].topic == "X"


def test_independent_produces_nothing(tmp_path):
    args = [_arg("A1", "X"), _arg("A2", "X")]
    client = FakeClient({frozenset({"A1", "A2"}): _resp("independent")})
    run = RunContext(name="test", base_dir=tmp_path)
    attacks, supports = detect_conflicts(args, client, run)
    assert attacks == []
    assert supports == []


def test_detect_conflicts_calls_llm_only_for_same_topic_pairs(tmp_path):
    """Singletons (no peer on the topic) skip the LLM entirely."""
    args = [
        _arg("A1", "X"),
        _arg("A2", "X"),
        _arg("A3", "DIFFERENT"),  # singleton
    ]
    client = FakeClient({frozenset({"A1", "A2"}): _resp("independent")})
    run = RunContext(name="test", base_dir=tmp_path)
    detect_conflicts(args, client, run)
    assert client.calls == [frozenset({"A1", "A2"})]


def test_detect_conflicts_handles_mixed_relations(tmp_path):
    """Three pairs in one run: one rebut, one support, one independent."""
    args = [
        _arg("A1", "X"),
        _arg("A2", "X"),
        _arg("A3", "X"),
    ]
    client = FakeClient({
        frozenset({"A1", "A2"}): _resp("rebutting"),
        frozenset({"A1", "A3"}): _resp("support"),
        frozenset({"A2", "A3"}): _resp("independent"),
    })
    run = RunContext(name="test", base_dir=tmp_path)
    attacks, supports = detect_conflicts(args, client, run)
    assert len(attacks) == 2          # rebut → 2 directed edges
    assert len(supports) == 1          # one support pair


def test_detect_conflicts_with_no_candidate_pairs(tmp_path):
    """No same-topic pairs → no LLM calls, empty results."""
    args = [_arg("A1", "X"), _arg("A2", "Y")]
    client = FakeClient({})
    run = RunContext(name="test", base_dir=tmp_path)
    attacks, supports = detect_conflicts(args, client, run)
    assert attacks == []
    assert supports == []
    assert client.calls == []
