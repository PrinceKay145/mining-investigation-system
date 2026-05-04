"""
v1 Decomposition — the entry point of the multi-agent pipeline.

Two modes (both return identical CaseFile objects, so v2–v6 are mode-agnostic):

  Mode 1 (primary): structured JSON input → validated CaseFile.
                    Used for thesis evaluation. Reads files where arguments
                    have already been extracted into the 8-field Toulmin schema.

  Mode 2 (demonstration): raw text → LLM extraction → CaseFile.
                          Deferred. Demonstrates the pipeline can ingest
                          unstructured text end-to-end. Implementation under
                          development in notebooks/v1_extract_arguments.ipynb.
"""

from __future__ import annotations

from pathlib import Path

from kb.loader import load_case_file
from schema.ground_truth import CaseFile

__all__ = ["decompose_from_json", "decompose_from_text"]


def decompose_from_json(case_path: Path | str) -> CaseFile:
    """
    v1 Mode 1 — load and validate a structured JSON case file.

    Args:
        case_path: Path to a case JSON file with arguments already
                   extracted into the 8-field Toulmin schema
                   (id, source, topic, claim, evidence, warrant,
                   confidence, cause_categories).

    Returns:
        CaseFile with `.arguments` (pipeline input for v2–v6) and
        `.ground_truth` (held aside for v5 evaluation; never fed to v2–v5).

    Raises:
        FileNotFoundError: if the file does not exist.
        pydantic.ValidationError: if any field fails schema validation.
        ValueError: if any argument lacks cause_categories.
    """
    return load_case_file(case_path)


def decompose_from_text(text: str) -> CaseFile:
    """
    v1 Mode 2 (NOT YET IMPLEMENTED) — LLM-assisted extraction from raw text.

    Will accept a raw report passage and use an LLM to extract structured
    arguments in the 8-field schema, returning the same CaseFile shape as
    Mode 1. Evaluated against manual extraction as ground truth.

    Until implemented, callers should use `decompose_from_json` with a
    pre-extracted JSON file.

    See notebooks/v1_extract_arguments.ipynb for the extraction workflow.
    """
    raise NotImplementedError(
        "v1 Mode 2 (LLM extraction) is not yet implemented. "
        "Use decompose_from_json with a pre-extracted JSON file, or see "
        "notebooks/v1_extract_arguments.ipynb for the extraction workflow."
    )
