"""Tests for the AF graph visualizer."""

import networkx as nx

from schema.v5_result import V5Result
from v6_report.visualizer import render_af_graph


def _v5_with_simple_af() -> V5Result:
    """V5 result whose af_graph is two connected nodes a → b."""
    G = nx.DiGraph()
    G.add_node("a", data={"id": "a"})
    G.add_node("b", data={"id": "b"})
    G.add_edge("a", "b", type="rebutting", attack_id="ATK-V5-001")
    return V5Result(
        af_graph=nx.node_link_data(G, edges="edges"),
        grounded_extension=["a"],
        accepted=["a"],
        ambiguous=[],
        rejected=["b"],
    )


def test_render_af_graph_creates_png(tmp_path):
    out = render_af_graph(_v5_with_simple_af(), tmp_path / "graph.png")
    assert out.is_file()
    # PNG magic bytes
    head = out.read_bytes()[:8]
    assert head == b"\x89PNG\r\n\x1a\n"


def test_render_af_graph_handles_empty_graph(tmp_path):
    """An empty AF should still render (zero nodes) without crashing."""
    G = nx.DiGraph()
    v5 = V5Result(af_graph=nx.node_link_data(G, edges="edges"))
    out = render_af_graph(v5, tmp_path / "empty.png")
    assert out.is_file()


def test_render_af_graph_handles_ambiguous_only(tmp_path):
    G = nx.DiGraph()
    G.add_node("x", data={"id": "x"})
    G.add_node("y", data={"id": "y"})
    G.add_edge("x", "y", type="undercutting", attack_id="ATK-V5-001")
    v5 = V5Result(
        af_graph=nx.node_link_data(G, edges="edges"),
        ambiguous=["x", "y"],
    )
    out = render_af_graph(v5, tmp_path / "ambig.png")
    assert out.is_file()
