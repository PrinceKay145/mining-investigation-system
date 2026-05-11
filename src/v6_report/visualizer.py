"""
Visualizer — render the v5 argumentation framework as a PNG.

Nodes are colored by acceptance:
  - green:  accepted (in grounded extension)
  - orange: ambiguous (in some preferred but not all)
  - red:    rejected (in no preferred extension)

Edges are styled by attack type:
  - solid red:    rebutting
  - dashed:       undercutting

Argument IDs are labels. Edge density on the Kostenko AF is modest enough
to plot directly with spring layout. For larger AFs, you'd want a more
sophisticated layout or filtering — out of scope for v6.

Uses matplotlib for rendering. Headless ("Agg" backend) so it runs in
scripts and CI without a display.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402

from schema.v5_result import V5Result


_COLOR_ACCEPTED = "#5cb85c"   # green
_COLOR_AMBIGUOUS = "#f0ad4e"  # orange
_COLOR_REJECTED = "#d9534f"   # red
_COLOR_NEUTRAL = "#bbbbbb"    # grey — for any node missed by classification


def render_af_graph(
    v5: V5Result,
    output_path: Path,
    *,
    title: str | None = None,
    figsize: tuple[float, float] = (14.0, 10.0),
    dpi: int = 150,
) -> Path:
    """
    Draw the argumentation framework as a PNG.

    Args:
        v5: the V5Result with `af_graph` (NetworkX node-link JSON).
        output_path: where to write the PNG.
        title: optional figure title.
        figsize, dpi: matplotlib figure controls.

    Returns:
        The path written (same as `output_path`).
    """
    G = nx.node_link_graph(v5.af_graph, edges="edges")

    accepted = set(v5.accepted)
    ambiguous = set(v5.ambiguous)
    rejected = set(v5.rejected)

    node_colors = []
    for n in G.nodes():
        if n in accepted:
            node_colors.append(_COLOR_ACCEPTED)
        elif n in ambiguous:
            node_colors.append(_COLOR_AMBIGUOUS)
        elif n in rejected:
            node_colors.append(_COLOR_REJECTED)
        else:
            node_colors.append(_COLOR_NEUTRAL)

    # Edge styling by attack type
    rebut_edges = [(u, v) for u, v, d in G.edges(data=True) if d.get("type") == "rebutting"]
    undercut_edges = [(u, v) for u, v, d in G.edges(data=True) if d.get("type") == "undercutting"]

    # Layout — spring layout works well for sparse-ish AFs
    pos = nx.spring_layout(G, k=1.4, iterations=80, seed=42)

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    nx.draw_networkx_nodes(
        G, pos, node_color=node_colors, node_size=900,
        edgecolors="black", linewidths=0.7, ax=ax,
    )
    nx.draw_networkx_labels(
        G, pos, font_size=7, font_color="black", ax=ax,
    )
    if rebut_edges:
        nx.draw_networkx_edges(
            G, pos, edgelist=rebut_edges,
            edge_color="#d9534f", width=1.5, alpha=0.85,
            arrows=True, arrowsize=14, ax=ax,
        )
    if undercut_edges:
        nx.draw_networkx_edges(
            G, pos, edgelist=undercut_edges,
            edge_color="#444444", width=1.2, alpha=0.75,
            style="dashed", arrows=True, arrowsize=14, ax=ax,
        )

    # Legend
    legend_handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=_COLOR_ACCEPTED,
                   markersize=12, label="Accepted (grounded)", markeredgecolor="black"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=_COLOR_AMBIGUOUS,
                   markersize=12, label="Ambiguous", markeredgecolor="black"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=_COLOR_REJECTED,
                   markersize=12, label="Rejected", markeredgecolor="black"),
        plt.Line2D([0], [0], color="#d9534f", lw=1.5, label="Rebutting attack"),
        plt.Line2D([0], [0], color="#444444", lw=1.2, linestyle="--",
                   label="Undercutting attack"),
    ]
    ax.legend(handles=legend_handles, loc="lower right", framealpha=0.95, fontsize=9)

    if title:
        ax.set_title(title, fontsize=14, pad=15)
    ax.set_axis_off()
    plt.tight_layout()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format="png", bbox_inches="tight")
    plt.close(fig)
    return output_path
