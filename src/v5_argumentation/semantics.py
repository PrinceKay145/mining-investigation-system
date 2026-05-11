"""
Dung's argumentation semantics — grounded + preferred extensions.

Grounded (skeptical, unique, always exists):
  Iterative fixpoint of the characteristic function F. Label arguments
  as IN (no attackers, or all attackers labeled OUT) or OUT (at least
  one attacker is IN). Iterate to a stable labelling. The grounded
  extension is the set of IN arguments.

Preferred (credulous, may be multiple):
  Maximal admissible sets — sets S that are conflict-free and where every
  member is defended by S. We compute these via connected-component
  decomposition + brute-force per component. The Cartesian product across
  components gives the global preferred extensions.

Component decomposition exploits the fact that NP-hardness of preferred
semantics is a worst-case statement; in practice argumentation frameworks
from mining accident investigations are sparse, so individual components
are small (Kostenko: largest expected component ~3-10 nodes).
"""

from __future__ import annotations

from itertools import combinations, product

import networkx as nx


# ---------------------------------------------------------------------------
# Grounded extension
# ---------------------------------------------------------------------------

def grounded_extension(G: nx.DiGraph) -> set[str]:
    """
    Compute the grounded extension via fixpoint labelling.

    An argument is IN if every attacker is OUT (or it has no attackers).
    An argument is OUT if at least one attacker is IN.
    Iterate until no labels change. Remaining unlabeled arguments are
    UNDECIDED and are not part of the grounded extension.

    The grounded extension is unique and always exists. Returns the set of
    IN argument IDs.
    """
    in_set: set[str] = set()
    out_set: set[str] = set()
    undec: set[str] = set(G.nodes())

    changed = True
    while changed:
        changed = False
        # Promote to IN: no attackers, or every attacker is OUT
        newly_in = {
            a for a in undec
            if set(G.predecessors(a)).issubset(out_set)
        }
        if newly_in:
            in_set |= newly_in
            undec -= newly_in
            changed = True

        # Promote to OUT: some attacker is IN
        newly_out = {
            a for a in undec
            if set(G.predecessors(a)) & in_set
        }
        if newly_out:
            out_set |= newly_out
            undec -= newly_out
            changed = True

    return in_set


# ---------------------------------------------------------------------------
# Preferred extensions
# ---------------------------------------------------------------------------

def _defends(S: frozenset[str], arg: str, G: nx.DiGraph) -> bool:
    """
    True iff S defends `arg`: every attacker of `arg` is itself attacked
    by some member of S.
    """
    for attacker in G.predecessors(arg):
        attackers_of_attacker = set(G.predecessors(attacker))
        if not (S & attackers_of_attacker):
            return False
    return True


def _is_conflict_free(S: frozenset[str], G: nx.DiGraph) -> bool:
    """No member of S attacks another member of S."""
    for a in S:
        if set(G.successors(a)) & S:
            return False
    return True


def _is_admissible(S: frozenset[str], G: nx.DiGraph) -> bool:
    """Conflict-free AND defends every member."""
    if not _is_conflict_free(S, G):
        return False
    return all(_defends(S, a, G) for a in S)


def _preferred_for_component(subG: nx.DiGraph) -> list[frozenset[str]]:
    """
    Enumerate maximal admissible sets within a single connected component
    of the AF.

    Brute force: enumerate all 2^n subsets, keep the admissible ones,
    then filter to maximal (no admissible superset).
    """
    nodes = list(subG.nodes())
    admissible: list[frozenset[str]] = []
    for r in range(len(nodes) + 1):
        for subset in combinations(nodes, r):
            S = frozenset(subset)
            if _is_admissible(S, subG):
                admissible.append(S)

    # Keep only maximal admissible sets (no strict superset is admissible)
    preferred: list[frozenset[str]] = []
    for S in admissible:
        if not any(S < T for T in admissible):
            preferred.append(S)
    return preferred


def preferred_extensions(
    G: nx.DiGraph,
    max_component_size: int = 20,
) -> list[set[str]]:
    """
    Compute all preferred extensions via connected-component decomposition.

    Args:
        G: the argumentation framework.
        max_component_size: hard limit on the size of any weakly-connected
                            component. Components larger than this raise
                            ValueError — brute force becomes infeasible
                            beyond 2^20 ~ 1M subsets.

    Returns:
        List of preferred extensions (sets of argument IDs). For a fully
        attack-free framework, this is [set(all_nodes)]. For an empty
        framework, this is [set()].
    """
    if G.number_of_nodes() == 0:
        return [set()]

    components = list(nx.weakly_connected_components(G))

    # Per-component preferred sets
    per_component: list[list[frozenset[str]]] = []
    for component in components:
        if len(component) > max_component_size:
            raise ValueError(
                f"Connected component of size {len(component)} exceeds "
                f"max_component_size={max_component_size}. Use a labelling-based "
                f"algorithm or raise the limit (brute-force scales 2^n)."
            )
        subG = G.subgraph(component)
        per_component.append(_preferred_for_component(subG))

    # Cartesian product across components
    result: list[set[str]] = []
    for combination in product(*per_component):
        merged: set[str] = set()
        for s in combination:
            merged |= s
        result.append(merged)
    return result


# ---------------------------------------------------------------------------
# Acceptance derivation
# ---------------------------------------------------------------------------

def derive_acceptance(
    grounded: set[str],
    preferred: list[set[str]],
    all_arguments: set[str],
) -> tuple[set[str], set[str], set[str]]:
    """
    Derive (accepted, rejected, ambiguous) from extensions.

    accepted  = grounded extension (skeptical conclusions)
    rejected  = arguments not in any preferred extension (defeated)
    ambiguous = arguments in some preferred but not all (genuinely contested)

    Note: an argument can be in the grounded extension AND in every preferred
    extension. The classification is hierarchical — grounded membership
    implies acceptance regardless of preferred status.
    """
    accepted = set(grounded)

    if not preferred:
        # No preferred extensions → every argument is rejected
        return accepted, set(all_arguments), set()

    in_some = set().union(*preferred)
    in_all = set.intersection(*preferred) if preferred else set()
    rejected = set(all_arguments) - in_some
    # Ambiguous: in some preferred but not all, and not already accepted via grounded
    ambiguous = (in_some - in_all) - accepted

    return accepted, rejected, ambiguous
