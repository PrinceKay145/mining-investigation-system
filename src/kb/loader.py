"""
KB loader — parses JSON knowledge base files and checks referential integrity.

Two entry points:
  load_regulatory_kb(path) → taxonomy dicts + precedent list
  load_case_file(path, ...)  → CaseFile with arguments + ground truth

Referential integrity (decision #2):
  Schemas are pure data contracts. The loader cross-checks that
  cause_categories and violated_regulations IDs on precedents and
  arguments reference IDs that actually exist in the loaded taxonomy.
  This keeps the models clean and catches dangling references early.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from schema.taxonomy import CauseCategory, AccidentType, Regulation
from schema.precedent import Precedent
from schema.argument import Argument
from schema.ground_truth import (
    AttackRelation, SupportRelation, OpenQuestion,
    GroundTruth, CaseMetadata, CaseFile,
)


# ---------------------------------------------------------------------------
# Regulatory KB loading
# ---------------------------------------------------------------------------

class RegulatoryKBData:
    """
    Parsed contents of a regulatory knowledge base file.

    Attributes are keyed dicts for O(1) lookup by ID, plus the precedent list.
    """

    def __init__(
        self,
        cause_categories: dict[str, CauseCategory],
        accident_types: dict[str, AccidentType],
        regulations: dict[str, Regulation],
        precedents: list[Precedent],
        industry_statistics: list[dict[str, Any]],
        metadata: dict[str, Any],
    ):
        self.cause_categories = cause_categories
        self.accident_types = accident_types
        self.regulations = regulations
        self.precedents = precedents
        self.industry_statistics = industry_statistics
        self.metadata = metadata


def _parse_cause_taxonomy(raw_taxonomy: dict) -> dict[str, CauseCategory]:
    """Parse both technical and organizational cause categories."""
    categories: dict[str, CauseCategory] = {}
    for tier_key in ["technical_cause_categories", "organizational_cause_categories"]:
        for entry in raw_taxonomy.get(tier_key, []):
            # Separate core fields from supplementary details
            core_keys = {"id", "label", "description"}
            details = {k: v for k, v in entry.items() if k not in core_keys}
            cat = CauseCategory(
                id=entry["id"],
                label=entry["label"],
                description=entry["description"],
                details=details if details else None,
            )
            categories[cat.id] = cat
    return categories


def _parse_accident_types(raw_types: list[dict]) -> dict[str, AccidentType]:
    """Parse accident type definitions."""
    return {at.id: at for at in (AccidentType(**entry) for entry in raw_types)}


def _parse_regulations(raw_regs: list[dict]) -> dict[str, Regulation]:
    """Parse regulation summaries."""
    return {reg.id: reg for reg in (Regulation(**entry) for entry in raw_regs)}


def _parse_precedents(raw_precedents: list[dict]) -> list[Precedent]:
    """Parse precedent case records."""
    return [Precedent(**entry) for entry in raw_precedents]


def load_regulatory_kb(path: Path | str) -> RegulatoryKBData:
    """
    Load and parse a regulatory knowledge base JSON file.

    Args:
        path: Path to the JSON file (e.g. rostechnadzor_regulatory_kb_v2.json)

    Returns:
        RegulatoryKBData with all parsed components

    Raises:
        FileNotFoundError: if the file doesn't exist
        ValidationError: if any entry fails Pydantic validation
    """
    path = Path(path)
    with open(path) as f:
        raw = json.load(f)

    domain = raw.get("domain_knowledge", {})

    cause_categories = _parse_cause_taxonomy(domain.get("cause_taxonomy", {}))
    accident_types = _parse_accident_types(
        domain.get("accident_type_definitions", {}).get("types", [])
    )
    regulations = _parse_regulations(
        domain.get("regulatory_requirements", [])
    )
    precedents = _parse_precedents(raw.get("accident_precedents", []))
    industry_statistics = raw.get("industry_statistics", [])
    metadata = raw.get("metadata", {})

    return RegulatoryKBData(
        cause_categories=cause_categories,
        accident_types=accident_types,
        regulations=regulations,
        precedents=precedents,
        industry_statistics=industry_statistics,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Case file loading
# ---------------------------------------------------------------------------

def load_case_file(
    path: Path | str,
    backfill_map: dict[str, list[str]] | None = None,
) -> CaseFile:
    """
    Load and parse a case file JSON (e.g. kostenko_knowledge_base.json).

    Args:
        path: Path to the JSON file
        backfill_map: Optional dict mapping argument IDs to cause_categories
                      lists. Used when the source JSON lacks cause_categories
                      (e.g. Kostenko KB before permanent backfill).

    Returns:
        CaseFile with arguments and ground truth

    Raises:
        FileNotFoundError: if the file doesn't exist
        ValidationError: if any entry fails Pydantic validation
        ValueError: if backfill_map is needed but missing for an argument
    """
    path = Path(path)
    with open(path) as f:
        raw = json.load(f)

    # --- Parse arguments ---
    arguments: list[Argument] = []
    for raw_arg in raw.get("arguments", []):
        # Check if cause_categories exists in source data
        if "cause_categories" in raw_arg and raw_arg["cause_categories"]:
            arg = Argument(**raw_arg)
        elif backfill_map and raw_arg["id"] in backfill_map:
            arg = Argument(
                id=raw_arg["id"],
                source=raw_arg["source"],
                topic=raw_arg["topic"],
                claim=raw_arg["claim"],
                evidence=raw_arg["evidence"],
                warrant=raw_arg["warrant"],
                confidence=raw_arg["confidence"],
                cause_categories=backfill_map[raw_arg["id"]],
            )
        else:
            raise ValueError(
                f"Argument '{raw_arg['id']}' has no cause_categories and no "
                f"backfill mapping provided. Either add cause_categories to "
                f"the source JSON or provide a backfill_map."
            )
        arguments.append(arg)

    # --- Parse ground truth ---
    af = raw.get("argumentation_framework", {})
    ground_truth = GroundTruth(
        attack_relations=[
            AttackRelation(**a) for a in af.get("attack_relations", [])
        ],
        support_relations=[
            SupportRelation(**s) for s in af.get("support_relations", [])
        ],
        open_questions=[
            OpenQuestion(**q) for q in af.get("open_questions", [])
        ],
    )

    # --- Parse metadata ---
    meta_raw = raw.get("metadata", {})
    # Separate known fields from extras
    known_meta_keys = {"case", "date", "location", "sources", "investigation_questions"}
    extra = {k: v for k, v in meta_raw.items() if k not in known_meta_keys}

    metadata = CaseMetadata(
        case=meta_raw.get("case", "Unknown"),
        date=meta_raw.get("date", "Unknown"),
        location=meta_raw.get("location", "Unknown"),
        sources=meta_raw.get("sources", []),
        investigation_questions=meta_raw.get("investigation_questions", []),
        extra=extra if extra else None,
    )

    return CaseFile(
        metadata=metadata,
        arguments=arguments,
        ground_truth=ground_truth,
    )


# ---------------------------------------------------------------------------
# Referential integrity checking
# ---------------------------------------------------------------------------

class IntegrityError:
    """A single referential integrity violation."""

    def __init__(self, entity_type: str, entity_id: str, field: str,
                 bad_ref: str, message: str):
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.field = field
        self.bad_ref = bad_ref
        self.message = message

    def __repr__(self) -> str:
        return f"IntegrityError({self.entity_type} {self.entity_id}: {self.message})"


def check_integrity(
    regulatory: RegulatoryKBData,
    case_file: CaseFile | None = None,
) -> list[IntegrityError]:
    """
    Cross-check referential integrity across loaded data.

    Checks:
      1. Precedent.cause_categories → cause category IDs exist in taxonomy
      2. Precedent.violated_regulations → regulation IDs exist
      3. Regulation.relevant_cause_categories → cause category IDs exist
      4. (If case_file) Argument.cause_categories → cause category IDs exist
      5. (If case_file) Ground truth attacker/target → argument IDs exist
      6. (If case_file) Ground truth supporter IDs → argument IDs exist

    Returns:
        List of IntegrityError objects (empty = all clean)
    """
    errors: list[IntegrityError] = []
    valid_cause_ids = set(regulatory.cause_categories.keys())
    valid_reg_ids = set(regulatory.regulations.keys())

    # 1. Precedent cause_categories
    for prec in regulatory.precedents:
        for cid in prec.cause_categories:
            if cid not in valid_cause_ids:
                errors.append(IntegrityError(
                    "Precedent", prec.id, "cause_categories", cid,
                    f"Cause category '{cid}' not found in taxonomy",
                ))

    # 2. Precedent violated_regulations
    for prec in regulatory.precedents:
        for rid in prec.violated_regulations:
            if rid not in valid_reg_ids:
                errors.append(IntegrityError(
                    "Precedent", prec.id, "violated_regulations", rid,
                    f"Regulation '{rid}' not found in taxonomy",
                ))

    # 3. Regulation.relevant_cause_categories
    for reg in regulatory.regulations.values():
        for cid in reg.relevant_cause_categories:
            if cid not in valid_cause_ids:
                errors.append(IntegrityError(
                    "Regulation", reg.id, "relevant_cause_categories", cid,
                    f"Cause category '{cid}' not found in taxonomy",
                ))

    # 4–6. Case file checks
    if case_file is not None:
        arg_ids = {a.id for a in case_file.arguments}

        # 4. Argument cause_categories
        for arg in case_file.arguments:
            for cid in arg.cause_categories:
                if cid not in valid_cause_ids:
                    errors.append(IntegrityError(
                        "Argument", arg.id, "cause_categories", cid,
                        f"Cause category '{cid}' not found in taxonomy",
                    ))

        # 5. Attack relations
        for atk in case_file.ground_truth.attack_relations:
            if atk.attacker not in arg_ids:
                errors.append(IntegrityError(
                    "AttackRelation", atk.id, "attacker", atk.attacker,
                    f"Attacker '{atk.attacker}' not in case arguments",
                ))
            if atk.target not in arg_ids:
                errors.append(IntegrityError(
                    "AttackRelation", atk.id, "target", atk.target,
                    f"Target '{atk.target}' not in case arguments",
                ))

        # 6. Support relations
        for sup in case_file.ground_truth.support_relations:
            for sid in sup.supporters:
                if sid not in arg_ids:
                    errors.append(IntegrityError(
                        "SupportRelation", sup.id, "supporters", sid,
                        f"Supporter '{sid}' not in case arguments",
                    ))

    return errors