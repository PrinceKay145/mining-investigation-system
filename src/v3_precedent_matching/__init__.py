"""
v3 Precedent matching — two-step CBR (case-based reasoning).

Algorithm (per architecture spec):
  Step 1 — Type filter: keep precedents whose accident_type matches the
           v2 primary_type or any v2 secondary_type. Drops obvious mismatches
           (e.g. slope_failure precedents when the case is a methane explosion).
  Step 2 — Jaccard scoring: overlap = |shared_categories| / |union_of_categories|
           between the case's cause_categories and each precedent's
           cause_categories. Ranks the type-matched precedents by overlap.

This is intentionally simpler than Markarian's full correspondence matrix —
serves the same purpose (identifying most relevant past cases) with a
mathematically clean, easily explainable score.

Precedent fingerprints via `similarity_profile` (the 25 boolean flags) are
NOT yet used by v3. They could be folded in as a tie-breaker in a future
revision once the case files carry their own profiles. Documented in note.md.
"""

from __future__ import annotations

from schema.classification import ClassificationResult
from schema.precedent import Precedent
from schema.precedent_match import PrecedentMatch, PrecedentMatchResult

__all__ = ["match_precedents"]


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard overlap. Returns 0.0 when both sets are empty (no division)."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def match_precedents(
    classification: ClassificationResult,
    precedents: list[Precedent],
    threshold: float = 0.0,
) -> PrecedentMatchResult:
    """
    Rank precedents by accident-type compatibility and Jaccard cause overlap.

    Args:
        classification: v2's `ClassificationResult` (primary + secondary types
                        and the case's aggregated cause_categories).
        precedents: precedent list (e.g. `kb.precedents`).
        threshold: minimum Jaccard score for inclusion. Default 0.0 keeps all
                   type-matched precedents — useful for funnel inspection.
                   Raise this for v6 reports where you want only meaningful
                   matches.

    Returns:
        PrecedentMatchResult with matches sorted by overlap_score descending,
        plus echoes of the v2 types used and funnel telemetry
        (total considered → passed type filter → after threshold).
    """
    primary = classification.primary_type
    secondaries = set(classification.secondary_types)

    # --- Step 1: type filter ---
    type_filtered: list[tuple[Precedent, str]] = []
    for prec in precedents:
        if prec.accident_type == primary:
            type_filtered.append((prec, "primary"))
        elif prec.accident_type in secondaries:
            type_filtered.append((prec, "secondary"))

    # --- Step 2: Jaccard scoring ---
    target_set = classification.all_cause_categories
    matches: list[PrecedentMatch] = []
    for prec, matched_via in type_filtered:
        prec_set = set(prec.cause_categories)
        score = _jaccard(target_set, prec_set)
        if score < threshold:
            continue
        matches.append(PrecedentMatch(
            precedent_id=prec.id,
            accident_type=prec.accident_type,
            overlap_score=score,
            shared_cause_categories=sorted(target_set & prec_set),
            matched_via=matched_via,  # type: ignore[arg-type]
        ))

    matches.sort(key=lambda m: m.overlap_score, reverse=True)

    return PrecedentMatchResult(
        matches=matches,
        primary_type=primary,
        secondary_types=classification.secondary_types,
        total_precedents=len(precedents),
        filtered_count=len(type_filtered),
    )
