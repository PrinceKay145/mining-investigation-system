"""
v5 conflict detection — hybrid topic filter + LLM confirmation.

Step 1: enumerate argument pairs sharing the same `topic` (exact string).
Step 2: for each pair, call the LLM with a structured prompt asking for
        the logical relationship: rebutting, undercutting (directional),
        support, or independent.

Each LLM call is independent and easily parallelizable via ThreadPoolExecutor.

Output: (attack_relations, support_relations) tuples ready for the AF
construction step. Rebutting becomes two directed attack edges (A→B and B→A);
undercutting becomes one directed edge in the indicated direction.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from llm import LLMClient
from llm.logging import RunContext
from prompts import load_prompt
from schema.argument import Argument
from schema.ground_truth import (
    AttackRelation, AttackType,
    SupportRelation, SupportStrength,
)


ConflictRelation = Literal[
    "rebutting",
    "undercutting_a_to_b",
    "undercutting_b_to_a",
    "support",
    "independent",
]


class ConflictDetectionResponse(BaseModel):
    """Schema for the LLM's structured response to one pair check."""

    relation: ConflictRelation
    rationale: str


# ---------------------------------------------------------------------------
# Step 1 — topic filter
# ---------------------------------------------------------------------------

def topic_filter(arguments: list[Argument]) -> list[tuple[Argument, Argument]]:
    """
    Return all argument pairs (A, B) where A.topic == B.topic (exact match).

    Order is preserved within each pair (A precedes B by their index in the
    input list) so the LLM's directional outputs (`undercutting_a_to_b`)
    map back to specific argument IDs unambiguously.
    """
    pairs: list[tuple[Argument, Argument]] = []
    for i, a in enumerate(arguments):
        for b in arguments[i + 1:]:
            if a.topic == b.topic:
                pairs.append((a, b))
    return pairs


# ---------------------------------------------------------------------------
# Step 2 — LLM confirmation (per pair)
# ---------------------------------------------------------------------------

def _slugify_model(model: str) -> str:
    """
    Make a model ID filesystem-safe by replacing `/` and `:` with `_`.

    Example: `openai/gpt-oss-20b:free` → `openai_gpt-oss-20b_free`.
    """
    return model.replace("/", "_").replace(":", "_")


def _cache_key(arg_a: Argument, arg_b: Argument, model: str) -> str:
    """
    Stable cache key based on (model, content hash).

    The cache key includes both:
      - a content hash of both arguments — so any change to either
        argument's fields invalidates the entry (no stale hits when v4
        produces different agent outputs in a re-run);
      - the LLM model string that confirmed the pair — so the same
        `(arg_a, arg_b)` pair confirmed by gpt-oss-20b does **not** return
        a cached gpt-oss-20b answer when the configured model is, say,
        gemini-2.5-flash. Each model gets its own cache namespace.

    The model-namespace property is the critical primitive for Axis 4
    (cross-model robustness): swapping `OPENROUTER_MODEL_V5_CONFIRMATION`
    forces fresh confirmations under the new model, exactly what the
    cross-model comparison requires.
    """
    content = json.dumps(
        [arg_a.model_dump(), arg_b.model_dump()],
        sort_keys=True, ensure_ascii=False,
    )
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    model_slug = _slugify_model(model)
    return f"{arg_a.id}__{arg_b.id}__{model_slug}__{h}"


def _cache_get(cache_dir: Path | None, key: str) -> ConflictDetectionResponse | None:
    """Read a cached response. Returns None on miss or corrupt cache file."""
    if cache_dir is None:
        return None
    path = cache_dir / f"{key}.json"
    if not path.is_file():
        return None
    try:
        return ConflictDetectionResponse.model_validate_json(path.read_text())
    except Exception:
        return None  # corrupt cache file → treat as miss


def _cache_put(cache_dir: Path | None, key: str, response: ConflictDetectionResponse) -> None:
    """Persist a response to the cache. No-op if cache_dir is None."""
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.json").write_text(response.model_dump_json(indent=2))


def _confirm_pair(
    arg_a: Argument,
    arg_b: Argument,
    client: LLMClient,
    run: RunContext,
    cache_dir: Path | None = None,
) -> ConflictDetectionResponse:
    """
    Run the v5_conflict_check prompt on one (A, B) pair.

    If `cache_dir` is provided, check the cache first; on miss, call the LLM
    and persist the response. The cache key is content-hash based so changes
    to argument content invalidate the cache automatically.
    """
    key = _cache_key(arg_a, arg_b, client.model)
    cached = _cache_get(cache_dir, key)
    if cached is not None:
        run.event(
            "v5_pair_cache_hit",
            arg_a=arg_a.id, arg_b=arg_b.id,
            relation=cached.relation,
            model=client.model,
        )
        return cached

    prompt = load_prompt("v5_conflict_check", arg_a=arg_a, arg_b=arg_b)
    run.event(
        "v5_pair_check_start",
        arg_a=arg_a.id,
        arg_b=arg_b.id,
        topic=arg_a.topic,
    )
    response = client.complete_json(
        prompt=prompt,
        schema=ConflictDetectionResponse,
        temperature=0.0,
    )
    run.event(
        "v5_pair_check_done",
        arg_a=arg_a.id,
        arg_b=arg_b.id,
        relation=response.relation,
        rationale=response.rationale[:200],
    )
    _cache_put(cache_dir, key, response)
    return response


# ---------------------------------------------------------------------------
# Step 3 — assemble AttackRelation / SupportRelation objects
# ---------------------------------------------------------------------------

def _assemble_relations(
    confirmed: list[tuple[Argument, Argument, ConflictDetectionResponse]],
) -> tuple[list[AttackRelation], list[SupportRelation]]:
    """
    Turn the per-pair LLM outputs into AttackRelation + SupportRelation lists.

    Rebutting becomes two directed attack edges.
    Undercutting becomes one directed edge in the indicated direction.
    Support becomes a SupportRelation (BILATERAL since pairwise).
    Independent is skipped.
    """
    attacks: list[AttackRelation] = []
    supports: list[SupportRelation] = []
    atk_seq = 0
    sup_seq = 0

    for arg_a, arg_b, resp in confirmed:
        rationale = resp.rationale
        if resp.relation == "rebutting":
            atk_seq += 1
            attacks.append(AttackRelation(
                id=f"ATK-V5-{atk_seq:03d}",
                attacker=arg_a.id, target=arg_b.id,
                type=AttackType.REBUTTING,
                description=rationale,
            ))
            atk_seq += 1
            attacks.append(AttackRelation(
                id=f"ATK-V5-{atk_seq:03d}",
                attacker=arg_b.id, target=arg_a.id,
                type=AttackType.REBUTTING,
                description=rationale,
            ))
        elif resp.relation == "undercutting_a_to_b":
            atk_seq += 1
            attacks.append(AttackRelation(
                id=f"ATK-V5-{atk_seq:03d}",
                attacker=arg_a.id, target=arg_b.id,
                type=AttackType.UNDERCUTTING,
                description=rationale,
            ))
        elif resp.relation == "undercutting_b_to_a":
            atk_seq += 1
            attacks.append(AttackRelation(
                id=f"ATK-V5-{atk_seq:03d}",
                attacker=arg_b.id, target=arg_a.id,
                type=AttackType.UNDERCUTTING,
                description=rationale,
            ))
        elif resp.relation == "support":
            sup_seq += 1
            supports.append(SupportRelation(
                id=f"SUP-V5-{sup_seq:03d}",
                supporters=[arg_a.id, arg_b.id],
                topic=arg_a.topic,
                description=rationale,
                strength=SupportStrength.BILATERAL,
            ))
        # independent: skip
    return attacks, supports


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_conflicts(
    arguments: list[Argument],
    client: LLMClient,
    run: RunContext,
    max_workers: int = 4,
    cache_dir: Path | None = None,
) -> tuple[list[AttackRelation], list[SupportRelation]]:
    """
    End-to-end conflict detection.

    Args:
        arguments: combined argument set (v1 experts + v4 agents).
        client: an LLMClient (AnthropicClient or OpenAIClient).
        run: RunContext for telemetry.
        max_workers: how many pairs to check in parallel. Default 4 (lower
                     than for v4 agents because v5 makes many small calls
                     in quick succession and can trip rate limits otherwise).
        cache_dir: if provided, persistent cache for confirmed pair responses.
                   Cache key is content-hashed so re-runs with identical
                   arguments skip the LLM entirely. Critical for resumability
                   after rate-limit interruptions.

    Returns:
        (attack_relations, support_relations).
    """
    pairs = topic_filter(arguments)
    run.event(
        "v5_topic_filter_done",
        argument_count=len(arguments),
        candidate_pair_count=len(pairs),
        cache_dir=cache_dir,
    )

    if not pairs:
        return [], []

    # Parallelize per-pair LLM calls. Order does not matter for relation
    # assembly because each pair is independent.
    confirmed: list[tuple[Argument, Argument, ConflictDetectionResponse]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_confirm_pair, a, b, client, run, cache_dir): (a, b)
            for a, b in pairs
        }
        for future in as_completed(futures):
            a, b = futures[future]
            response = future.result()
            confirmed.append((a, b, response))

    attacks, supports = _assemble_relations(confirmed)
    return attacks, supports
