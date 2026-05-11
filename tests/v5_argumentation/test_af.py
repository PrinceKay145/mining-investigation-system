"""Tests for AF construction and serialization."""

from schema.argument import Argument
from schema.ground_truth import AttackRelation, AttackType
from v5_argumentation.af import build_af, af_to_dict


def _arg(arg_id: str, topic: str = "test", source: str = "X") -> Argument:
    return Argument(
        id=arg_id, source=source, topic=topic,
        claim="c", evidence="e", warrant="w",
        confidence=0.5, cause_categories=["TC-01"],
    )


def _atk(atk_id: str, attacker: str, target: str,
         type_: AttackType = AttackType.REBUTTING) -> AttackRelation:
    return AttackRelation(
        id=atk_id, attacker=attacker, target=target,
        type=type_, description="test",
    )


def test_build_af_adds_all_arguments_as_nodes():
    args = [_arg("a1"), _arg("a2"), _arg("a3")]
    G = build_af(args, attacks=[])
    assert set(G.nodes()) == {"a1", "a2", "a3"}
    assert G.number_of_edges() == 0


def test_build_af_attaches_argument_data_to_nodes():
    args = [_arg("a1", topic="ignition")]
    G = build_af(args, attacks=[])
    assert G.nodes["a1"]["data"]["topic"] == "ignition"


def test_build_af_adds_attack_edges():
    args = [_arg("a1"), _arg("a2")]
    attacks = [_atk("ATK-01", "a1", "a2")]
    G = build_af(args, attacks)
    assert G.number_of_edges() == 1
    assert G.has_edge("a1", "a2")
    assert G.edges["a1", "a2"]["type"] == "rebutting"
    assert G.edges["a1", "a2"]["attack_id"] == "ATK-01"


def test_build_af_skips_edges_with_unknown_nodes():
    """Attack referencing a node not in arguments is silently skipped."""
    args = [_arg("a1")]
    attacks = [_atk("ATK-01", "a1", "GHOST")]
    G = build_af(args, attacks)
    assert G.number_of_edges() == 0


def test_build_af_distinguishes_attack_types():
    args = [_arg("a1"), _arg("a2"), _arg("a3")]
    attacks = [
        _atk("ATK-1", "a1", "a2", AttackType.REBUTTING),
        _atk("ATK-2", "a2", "a3", AttackType.UNDERCUTTING),
    ]
    G = build_af(args, attacks)
    assert G.edges["a1", "a2"]["type"] == "rebutting"
    assert G.edges["a2", "a3"]["type"] == "undercutting"


def test_af_to_dict_round_trips_via_networkx():
    """The serialized graph should be re-readable by NetworkX."""
    import networkx as nx
    args = [_arg("a1"), _arg("a2")]
    attacks = [_atk("ATK-01", "a1", "a2")]
    G = build_af(args, attacks)
    data = af_to_dict(G)
    # Basic structure
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1
    # Re-read with NetworkX
    G2 = nx.node_link_graph(data, edges="edges")
    assert set(G2.nodes()) == {"a1", "a2"}
    assert G2.has_edge("a1", "a2")
