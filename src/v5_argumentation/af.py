"""
Argumentation Framework — NetworkX DiGraph construction and serialization.

Nodes are argument IDs, with the full Argument data attached as the `data`
attribute. Edges are directed attacks with `type` ("rebutting" or
"undercutting") and `attack_id` attributes.

Supports are NOT stored in the AF (Dung's framework is attack-only). v5
keeps supports as a separate list passed alongside the graph.
"""

from __future__ import annotations

import networkx as nx

from schema.argument import Argument
from schema.ground_truth import AttackRelation


def build_af(
    arguments: list[Argument],
    attacks: list[AttackRelation],
) -> nx.DiGraph:
    """
    Construct the AF DiGraph from arguments and attacks.

    Args:
        arguments: every argument becomes a node, even those with no edges.
        attacks: each attack becomes a directed edge from attacker to target.
                 Attacks referencing IDs not in `arguments` are skipped with
                 no error (caller's job to enforce referential integrity).

    Returns:
        A NetworkX DiGraph ready for semantics computation.
    """
    G = nx.DiGraph()
    for arg in arguments:
        G.add_node(arg.id, data=arg.model_dump(mode="json"))

    for atk in attacks:
        if G.has_node(atk.attacker) and G.has_node(atk.target):
            G.add_edge(
                atk.attacker,
                atk.target,
                type=atk.type.value,
                attack_id=atk.id,
            )
    return G


def af_to_dict(G: nx.DiGraph) -> dict:
    """Serialize the AF as node-link JSON for persistence in V5Result."""
    return nx.node_link_data(G, edges="edges")
