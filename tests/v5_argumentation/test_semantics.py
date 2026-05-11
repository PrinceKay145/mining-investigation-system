"""
Tests for Dung's semantics — grounded and preferred extensions.

Uses small synthetic AFs from the argumentation literature so the expected
outputs can be verified by hand. No LLM involvement.
"""

import networkx as nx
import pytest

from v5_argumentation.semantics import (
    derive_acceptance,
    grounded_extension,
    preferred_extensions,
)


def _af(edges: list[tuple[str, str]], nodes: list[str] | None = None) -> nx.DiGraph:
    """Tiny helper to build a DiGraph from a list of (attacker, target) edges."""
    G = nx.DiGraph()
    if nodes:
        G.add_nodes_from(nodes)
    G.add_edges_from(edges)
    return G


# ---------------------------------------------------------------------------
# Grounded extension
# ---------------------------------------------------------------------------

def test_grounded_empty():
    assert grounded_extension(nx.DiGraph()) == set()


def test_grounded_unattacked_args_are_in():
    G = _af([], nodes=["a", "b", "c"])
    assert grounded_extension(G) == {"a", "b", "c"}


def test_grounded_chain_of_attacks():
    """a → b → c → d. Grounded: {a, c}."""
    G = _af([("a", "b"), ("b", "c"), ("c", "d")])
    assert grounded_extension(G) == {"a", "c"}


def test_grounded_two_cycle_is_undecided():
    """a ↔ b (mutual attack). Neither is in the grounded extension."""
    G = _af([("a", "b"), ("b", "a")])
    assert grounded_extension(G) == set()


def test_grounded_three_cycle_is_undecided():
    """a → b → c → a. No fixpoint progress; all undecided."""
    G = _af([("a", "b"), ("b", "c"), ("c", "a")])
    assert grounded_extension(G) == set()


def test_grounded_defended_by_root():
    """root → attacker → target. Root and target are IN, attacker is OUT."""
    G = _af([("root", "attacker"), ("attacker", "target")])
    assert grounded_extension(G) == {"root", "target"}


# ---------------------------------------------------------------------------
# Preferred extensions
# ---------------------------------------------------------------------------

def test_preferred_empty():
    assert preferred_extensions(nx.DiGraph()) == [set()]


def test_preferred_unattacked_args():
    G = _af([], nodes=["a", "b", "c"])
    pref = preferred_extensions(G)
    assert pref == [{"a", "b", "c"}]


def test_preferred_two_cycle_yields_two_extensions():
    """a ↔ b. Two preferred extensions: {a} and {b}."""
    G = _af([("a", "b"), ("b", "a")])
    pref = preferred_extensions(G)
    # Order may vary
    assert {frozenset(p) for p in pref} == {frozenset({"a"}), frozenset({"b"})}


def test_preferred_chain():
    """a → b → c → d. The grounded extension {a, c} is the unique preferred."""
    G = _af([("a", "b"), ("b", "c"), ("c", "d")])
    pref = preferred_extensions(G)
    assert pref == [{"a", "c"}]


def test_preferred_disconnected_components_cartesian_product():
    """Two independent 2-cycles → 4 preferred extensions (Cartesian product)."""
    G = _af([("a", "b"), ("b", "a"), ("x", "y"), ("y", "x")])
    pref = preferred_extensions(G)
    pref_sets = {frozenset(p) for p in pref}
    assert pref_sets == {
        frozenset({"a", "x"}),
        frozenset({"a", "y"}),
        frozenset({"b", "x"}),
        frozenset({"b", "y"}),
    }


def test_preferred_component_size_limit():
    """Components beyond the limit raise — guards against runaway brute force."""
    # 5-cycle is one weakly-connected component of size 5
    G = _af([("a", "b"), ("b", "c"), ("c", "d"), ("d", "e"), ("e", "a")])
    with pytest.raises(ValueError, match="exceeds max_component_size"):
        preferred_extensions(G, max_component_size=4)


# ---------------------------------------------------------------------------
# Derive acceptance
# ---------------------------------------------------------------------------

def test_derive_acceptance_consensus():
    """When grounded == preferred (single ext.), accepted = grounded, rest rejected."""
    grounded = {"a", "c"}
    preferred = [{"a", "c"}]
    all_args = {"a", "b", "c", "d"}
    accepted, rejected, ambiguous = derive_acceptance(grounded, preferred, all_args)
    assert accepted == {"a", "c"}
    assert rejected == {"b", "d"}
    assert ambiguous == set()


def test_derive_acceptance_with_ambiguity():
    """grounded ⊂ preferred (multiple ext.) → some args are ambiguous."""
    grounded: set[str] = set()
    preferred = [{"a"}, {"b"}]
    all_args = {"a", "b", "c"}
    accepted, rejected, ambiguous = derive_acceptance(grounded, preferred, all_args)
    assert accepted == set()
    assert rejected == {"c"}
    assert ambiguous == {"a", "b"}


def test_derive_acceptance_no_preferred():
    """No preferred extensions → everything rejected."""
    grounded: set[str] = set()
    preferred: list[set[str]] = []
    all_args = {"a", "b"}
    accepted, rejected, ambiguous = derive_acceptance(grounded, preferred, all_args)
    assert accepted == set()
    assert rejected == {"a", "b"}
    assert ambiguous == set()
