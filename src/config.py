"""
Project configuration — paths, constants, and defaults.

All paths resolve from PROJECT_ROOT using pathlib so the code works
on any machine, not just the drafting container.
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Project root — two levels up from src/config.py
# ---------------------------------------------------------------------------

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Default KB paths (relative to PROJECT_ROOT)
# ---------------------------------------------------------------------------

DEFAULT_KB_DIR: Path = PROJECT_ROOT / "data" / "knowledge_base"
DEFAULT_REGULATORY_KB: Path = DEFAULT_KB_DIR / "rostechnadzor_regulatory_kb_v2.json"
DEFAULT_KOSTENKO_KB: Path = DEFAULT_KB_DIR / "kostenko_knowledge_base.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Referential integrity: cause category ID format
CAUSE_CATEGORY_PATTERN = r"^(TC|OC)-\d{2}$"

# Referential integrity: regulation ID format
REGULATION_PATTERN = r"^REG-\d{2}$"

# CBR matching threshold (from Markarian & Temkin 2024)
DEFAULT_CBR_THRESHOLD: float = 0.8

# SimilarityProfile boolean flag names (for iteration in v3 matching)
SIMILARITY_BOOL_FLAGS: list[str] = [
    "underground",
    "longwall_face_involved",
    "methane_involved",
    "companion_seam_involved",
    "goaf_accumulation",
    "coal_dust_involved",
    "spontaneous_combustion_involved",
    "ignition_source_identified",
    "ventilation_failure",
    "degasification_failure",
    "outburst_hazard",
    "geological_hazard",
    "seismic_event",
    "roof_failure",
    "monitoring_failure",
    "data_falsification",
    "naryad_violation",
    "insufficient_supervision",
    "qualification_failure",
    "mass_casualty",
]