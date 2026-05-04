"""
v2 Identification — accident type classification from cause categories.

Method: rule-based aggregation. The cause_id → accident_type mapping is
derived at runtime from the regulatory KB itself (no hand-coded table).
For each regulation, the Cartesian product of its `relevant_cause_categories`
× `applies_to_accident_types` contributes one (cause, type) pair to the
mapping. Regulations whose `applies_to_accident_types == ["all"]` are excluded
because they apply to every type and so do not disambiguate (e.g. REG-08
naryad system, REG-09 production control).

Per the architecture spec, v2 is intentionally simple — classification is
not the thesis contribution. A production system would use a trained ML
classifier per Markarian et al. 2025.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from schema.argument import Argument
from schema.classification import ClassificationResult
from schema.taxonomy import Regulation

__all__ = ["classify", "build_cause_to_type_index"]

# Sentinel used in the regulatory KB for type-agnostic regulations
_ALL_TYPES_SENTINEL = "all"


def build_cause_to_type_index(
    regulations: dict[str, Regulation],
) -> dict[str, set[str]]:
    """
    Build a sparse mapping `cause_id → set of associated accident types`,
    derived from the regulations dict (e.g. `kb.regulations`).

    Regulations that apply to all accident types are excluded — they don't
    help disambiguate type. A cause that only appears in such regulations
    (e.g. OC-01 production control) will be absent from the index.
    """
    index: dict[str, set[str]] = {}
    for reg in regulations.values():
        types = [
            t for t in reg.applies_to_accident_types
            if t != _ALL_TYPES_SENTINEL
        ]
        if not types:
            continue
        for cid in reg.relevant_cause_categories:
            index.setdefault(cid, set()).update(types)
    return index


def classify(
    arguments: Iterable[Argument],
    regulations: dict[str, Regulation],
    secondary_threshold: float = 0.5,
) -> ClassificationResult:
    """
    Classify the dominant accident type across a set of arguments.

    Args:
        arguments: arguments from a v1 CaseFile (typically `case.arguments`)
        regulations: regulatory dict (e.g. `kb.regulations` or
                     `RegulatoryKBData.regulations`)
        secondary_threshold: a type qualifies as secondary if its vote
                             count is at least this fraction of the top
                             type's vote count. Default 0.5.

    Returns:
        ClassificationResult with primary_type, secondary_types, cause_profile,
        and type_votes (the latter two for transparency / v3 / reporting).
    """
    index = build_cause_to_type_index(regulations)
    cause_profile: Counter[str] = Counter()
    type_votes: Counter[str] = Counter()

    for arg in arguments:
        for cid in arg.cause_categories:
            cause_profile[cid] += 1
            for accident_type in index.get(cid, ()):
                type_votes[accident_type] += 1

    if not type_votes:
        return ClassificationResult(
            primary_type="unknown",
            secondary_types=[],
            cause_profile=dict(cause_profile),
            type_votes={},
        )

    most_common = type_votes.most_common()
    primary, top_count = most_common[0]
    cutoff = secondary_threshold * top_count
    secondaries = [t for t, c in most_common[1:] if c >= cutoff]

    return ClassificationResult(
        primary_type=primary,
        secondary_types=secondaries,
        cause_profile=dict(cause_profile),
        type_votes=dict(type_votes),
    )
