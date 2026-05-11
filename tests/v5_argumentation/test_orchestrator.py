"""Tests for the v5 orchestrator — end-to-end with a mocked LLM client."""

import json

from llm.logging import RunContext
from schema.argument import Argument
from v5_argumentation import run_v5

from tests.v5_argumentation.test_conflict_detection import FakeClient, _resp


def _arg(arg_id: str, topic: str = "Ignition source", source: str = "X") -> Argument:
    return Argument(
        id=arg_id, source=source, topic=topic,
        claim=f"claim {arg_id}", evidence="e", warrant="w",
        confidence=0.5, cause_categories=["TC-01"],
    )


def test_run_v5_returns_v5_result_with_consensus(tmp_path):
    """Two args supporting each other → grounded == preferred == {A1, A2}."""
    args = [_arg("A1"), _arg("A2")]
    client = FakeClient({frozenset({"A1", "A2"}): _resp("support")})
    run = RunContext(name="v5test", base_dir=tmp_path)

    result = run_v5(arguments=args, client=client, run=run, cache_dir=None)

    assert set(result.accepted) == {"A1", "A2"}
    assert result.rejected == []
    assert result.ambiguous == []
    assert result.grounded_equals_preferred is True
    assert len(result.support_relations) == 1
    assert result.attack_relations == []


def test_run_v5_rebutting_produces_genuine_ambiguity(tmp_path):
    """Two rebutting args → no grounded acceptance, two preferred extensions."""
    args = [_arg("A1"), _arg("A2")]
    client = FakeClient({frozenset({"A1", "A2"}): _resp("rebutting")})
    run = RunContext(name="v5test", base_dir=tmp_path)

    result = run_v5(arguments=args, client=client, run=run, cache_dir=None)

    assert result.accepted == []
    assert result.rejected == []
    assert set(result.ambiguous) == {"A1", "A2"}
    assert result.grounded_equals_preferred is False
    assert len(result.preferred_extensions) == 2


def test_run_v5_undercutting_produces_directed_attack(tmp_path):
    """A1 undercuts A2 → grounded = {A1}, A2 rejected."""
    args = [_arg("A1"), _arg("A2")]
    client = FakeClient({frozenset({"A1", "A2"}): _resp("undercutting_a_to_b")})
    run = RunContext(name="v5test", base_dir=tmp_path)

    result = run_v5(arguments=args, client=client, run=run, cache_dir=None)

    assert result.accepted == ["A1"]
    assert result.rejected == ["A2"]
    assert result.ambiguous == []


def test_run_v5_persists_result_artifact(tmp_path):
    args = [_arg("A1"), _arg("A2")]
    client = FakeClient({frozenset({"A1", "A2"}): _resp("independent")})
    run = RunContext(name="v5test", base_dir=tmp_path)

    run_v5(arguments=args, client=client, run=run, cache_dir=None)

    v5_path = run.dir / "v5_result.json"
    assert v5_path.is_file()
    data = json.loads(v5_path.read_text())
    assert "grounded_extension" in data
    assert "preferred_extensions" in data
    assert "af_graph" in data


def test_run_v5_logs_pipeline_events(tmp_path):
    args = [_arg("A1"), _arg("A2")]
    client = FakeClient({frozenset({"A1", "A2"}): _resp("rebutting")})
    run = RunContext(name="v5test", base_dir=tmp_path)

    run_v5(arguments=args, client=client, run=run, cache_dir=None)

    events = [
        json.loads(line)
        for line in (run.dir / "events.jsonl").read_text().splitlines()
    ]
    event_types = {e["event"] for e in events}
    assert {
        "v5_start",
        "v5_topic_filter_done",
        "v5_pair_check_start",
        "v5_pair_check_done",
        "v5_conflicts_done",
        "v5_af_built",
        "v5_semantics_done",
        "v5_done",
    }.issubset(event_types)


def test_run_v5_handles_no_conflicts(tmp_path):
    """No same-topic peers → no LLM calls, all args accepted, no attacks."""
    args = [_arg("A1", topic="X"), _arg("A2", topic="Y")]
    client = FakeClient({})  # no responses needed
    run = RunContext(name="v5test", base_dir=tmp_path)

    result = run_v5(arguments=args, client=client, run=run, cache_dir=None)

    assert set(result.accepted) == {"A1", "A2"}
    assert result.attack_relations == []
    assert result.support_relations == []
    assert result.grounded_equals_preferred is True


def test_run_v5_three_way_attack_produces_extensions(tmp_path):
    """A1↔A2 ↔A3 with mutual rebuttals on the same topic.

    For 3 args all rebutting each other (clique), no preferred extension
    can include >1 since they all attack each other. Preferred = [{A1},{A2},{A3}].
    """
    args = [_arg(a) for a in ("A1", "A2", "A3")]
    client = FakeClient({
        frozenset({"A1", "A2"}): _resp("rebutting"),
        frozenset({"A1", "A3"}): _resp("rebutting"),
        frozenset({"A2", "A3"}): _resp("rebutting"),
    })
    run = RunContext(name="v5test", base_dir=tmp_path)

    result = run_v5(arguments=args, client=client, run=run, cache_dir=None)

    assert result.accepted == []
    assert set(result.ambiguous) == {"A1", "A2", "A3"}
    assert {frozenset(p) for p in result.preferred_extensions} == {
        frozenset({"A1"}), frozenset({"A2"}), frozenset({"A3"}),
    }
