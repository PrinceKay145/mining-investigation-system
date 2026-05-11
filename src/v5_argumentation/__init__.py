"""
v5 Argumentation — Dung's framework over the combined argument set.

Pipeline:
  1. Detect attacks + supports via topic filter + LLM confirmation.
  2. Build the argumentation framework (NetworkX DiGraph).
  3. Compute the grounded and preferred extensions.
  4. Derive accepted / rejected / ambiguous from those extensions.
  5. Persist the V5Result + the NetworkX graph as artifacts.

The orchestrator takes the combined argument set (v1 experts + v4 agents)
and an LLMClient. It returns a V5Result and saves it to runs/<run_id>/.
"""

from __future__ import annotations

from pathlib import Path

from config import RUNS_DIR
from llm import LLMClient
from llm.logging import RunContext
from schema.argument import Argument
from schema.v5_result import V5Result
from v5_argumentation.af import build_af, af_to_dict
from v5_argumentation.conflict_detection import detect_conflicts
from v5_argumentation.semantics import (
    derive_acceptance,
    grounded_extension,
    preferred_extensions,
)

# Shared cache for v5 pair confirmations across runs.
# Living under runs/ inherits .gitignore. Content-hashed keys so different
# cases don't collide and stale arguments invalidate cleanly.
DEFAULT_V5_CACHE_DIR: Path = RUNS_DIR / "_pair_cache"

__all__ = ["run_v5", "V5Result"]


def run_v5(
    *,
    arguments: list[Argument],
    client: LLMClient,
    run: RunContext,
    max_workers: int = 4,
    max_component_size: int = 20,
    cache_dir: Path | None | object = ...,
) -> V5Result:
    """
    Run the v5 argumentation framework over the combined argument set.

    Args:
        arguments: combined v1 expert + v4 agent arguments.
        client: an LLMClient for conflict-pair confirmation.
        run: RunContext for telemetry + artifact persistence.
        max_workers: parallelism for the per-pair LLM confirmation step.
                     Default 4 (lower than v4's 3-way parallel agent calls
                     because v5 makes many small calls in quick succession,
                     which trips rate limits if too parallel).
        max_component_size: hard limit for preferred semantics brute force.
        cache_dir: persistent cache for confirmed pair responses (content-hashed
                   keys so re-runs are free for unchanged pairs). Defaults to
                   `DEFAULT_V5_CACHE_DIR` (= `runs/_pair_cache/`). Pass `None`
                   to disable caching entirely.

    Returns:
        V5Result with attacks, supports, extensions, acceptance derivation,
        and the serialized AF graph. Also written to runs/<run_id>/v5_result.json.
    """
    # Sentinel-based default so callers can pass cache_dir=None to disable
    if cache_dir is ...:
        cache_dir = DEFAULT_V5_CACHE_DIR

    run.event("v5_start", argument_count=len(arguments), cache_dir=cache_dir)

    # --- Step 1: conflict detection ---
    attacks, supports = detect_conflicts(
        arguments=arguments,
        client=client,
        run=run,
        max_workers=max_workers,
        cache_dir=cache_dir,
    )
    run.event(
        "v5_conflicts_done",
        attack_count=len(attacks),
        support_count=len(supports),
    )

    # --- Step 2: AF construction ---
    G = build_af(arguments, attacks)
    run.event(
        "v5_af_built",
        nodes=G.number_of_nodes(),
        edges=G.number_of_edges(),
    )

    # --- Step 3: semantics ---
    grounded = grounded_extension(G)
    preferred = preferred_extensions(G, max_component_size=max_component_size)
    run.event(
        "v5_semantics_done",
        grounded_size=len(grounded),
        preferred_count=len(preferred),
        preferred_sizes=[len(p) for p in preferred],
    )

    # --- Step 4: derive acceptance ---
    all_ids = {a.id for a in arguments}
    accepted, rejected, ambiguous = derive_acceptance(grounded, preferred, all_ids)

    # --- Step 5: assemble + persist ---
    result = V5Result(
        attack_relations=attacks,
        support_relations=supports,
        grounded_extension=sorted(grounded),
        preferred_extensions=[sorted(p) for p in preferred],
        accepted=sorted(accepted),
        rejected=sorted(rejected),
        ambiguous=sorted(ambiguous),
        af_graph=af_to_dict(G),
    )
    run.save_artifact("v5_result", result)
    run.event(
        "v5_done",
        accepted=len(accepted),
        rejected=len(rejected),
        ambiguous=len(ambiguous),
        consensus=result.grounded_equals_preferred,
    )
    return result
