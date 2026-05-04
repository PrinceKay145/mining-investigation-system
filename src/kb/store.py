"""
KnowledgeBase — in-memory store aggregating all loaded data.

The central KB from Markarian's architecture (БЗ in the directed graph
G = {V, E}). Every subsystem reads from this store.

Provides:
  - O(1) lookup by ID for cause categories, accident types, regulations
  - Precedent list for v3 CBR matching
  - Case file(s) for pipeline input and evaluation
  - Factory method from_files() for one-line loading
"""

from __future__ import annotations

from pathlib import Path

from schema.taxonomy import CauseCategory, AccidentType, Regulation
from schema.precedent import Precedent
from schema.ground_truth import CaseFile
from kb.loader import (
    RegulatoryKBData,
    load_regulatory_kb,
    load_case_file,
    check_integrity,
    IntegrityError,
)


class KnowledgeBase:
    """
    In-memory knowledge base aggregating regulatory data and case files.

    Usage:
        kb = KnowledgeBase.from_files(
            regulatory_path="data/rostechnadzor_regulatory_kb_v2.json",
            case_path="data/kostenko_knowledge_base.json",
            backfill_map={...},
        )

        # Lookups
        cat = kb.get_cause_category("TC-01")
        reg = kb.get_regulation("REG-05")
        precs = kb.precedents

        # Case
        case = kb.case_files["kostenko"]
        args = case.arguments
    """

    def __init__(self, regulatory: RegulatoryKBData):
        self._regulatory = regulatory
        self._case_files: dict[str, CaseFile] = {}

    # --- Factory ---

    @classmethod
    def from_files(
        cls,
        regulatory_path: Path | str,
        case_path: Path | str | None = None,
        case_name: str = "default",
        backfill_map: dict[str, list[str]] | None = None,
        strict: bool = True,
    ) -> "KnowledgeBase":
        """
        Load a KnowledgeBase from files in one call.

        Args:
            regulatory_path: Path to the regulatory KB JSON
            case_path: Optional path to a case file JSON
            case_name: Key for the case file in the store
            backfill_map: Optional cause_categories backfill for case arguments
            strict: If True, raise on referential integrity errors

        Returns:
            Populated KnowledgeBase

        Raises:
            ValueError: if strict=True and integrity errors are found
        """
        regulatory = load_regulatory_kb(regulatory_path)
        kb = cls(regulatory)

        if case_path is not None:
            case = load_case_file(case_path, backfill_map=backfill_map)
            kb.add_case_file(case_name, case)

        # Referential integrity check
        errors = kb.check_integrity()
        if errors and strict:
            error_msgs = "\n  ".join(repr(e) for e in errors)
            raise ValueError(
                f"Referential integrity errors ({len(errors)}):\n  {error_msgs}"
            )

        return kb

    # --- Case file management ---

    def add_case_file(self, name: str, case_file: CaseFile) -> None:
        """Add a case file to the store."""
        self._case_files[name] = case_file

    @property
    def case_files(self) -> dict[str, CaseFile]:
        return self._case_files

    # --- Taxonomy lookups ---

    @property
    def cause_categories(self) -> dict[str, CauseCategory]:
        return self._regulatory.cause_categories

    @property
    def accident_types(self) -> dict[str, AccidentType]:
        return self._regulatory.accident_types

    @property
    def regulations(self) -> dict[str, Regulation]:
        return self._regulatory.regulations

    @property
    def precedents(self) -> list[Precedent]:
        return self._regulatory.precedents

    @property
    def industry_statistics(self) -> list[dict]:
        return self._regulatory.industry_statistics

    def get_cause_category(self, cat_id: str) -> CauseCategory | None:
        """Look up a cause category by ID. Returns None if not found."""
        return self._regulatory.cause_categories.get(cat_id)

    def get_accident_type(self, type_id: str) -> AccidentType | None:
        """Look up an accident type by ID. Returns None if not found."""
        return self._regulatory.accident_types.get(type_id)

    def get_regulation(self, reg_id: str) -> Regulation | None:
        """Look up a regulation by ID. Returns None if not found."""
        return self._regulatory.regulations.get(reg_id)

    # --- Precedent filtering ---

    def precedents_by_type(self, accident_type: str) -> list[Precedent]:
        """Filter precedents by accident type label (v3 step 1)."""
        return [
            p for p in self._regulatory.precedents
            if p.accident_type == accident_type
        ]

    def precedents_by_cause(self, cause_id: str) -> list[Precedent]:
        """Filter precedents that include a specific cause category."""
        return [
            p for p in self._regulatory.precedents
            if cause_id in p.cause_categories
        ]

    # --- Integrity ---

    def check_integrity(self) -> list[IntegrityError]:
        """Run referential integrity checks across all loaded data."""
        all_errors: list[IntegrityError] = []
        for case in self._case_files.values():
            all_errors.extend(
                check_integrity(self._regulatory, case_file=case)
            )
        # Also check regulatory-internal integrity (regs → cause categories)
        if not self._case_files:
            all_errors.extend(check_integrity(self._regulatory))
        return all_errors

    # --- Summary ---

    def summary(self) -> dict:
        """Quick overview of what's loaded."""
        return {
            "cause_categories": len(self._regulatory.cause_categories),
            "accident_types": len(self._regulatory.accident_types),
            "regulations": len(self._regulatory.regulations),
            "precedents": len(self._regulatory.precedents),
            "case_files": list(self._case_files.keys()),
            "total_arguments": sum(
                len(cf.arguments) for cf in self._case_files.values()
            ),
        }