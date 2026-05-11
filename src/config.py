"""
Project configuration — paths, constants, and defaults.

All paths resolve from PROJECT_ROOT using pathlib so the code works
on any machine, not just the drafting container.

Imports `.env` (if present) at module load via python-dotenv, so any
module that imports config has env vars available.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Project root — two levels up from src/config.py
# ---------------------------------------------------------------------------

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# Load .env at import time. override=False so existing shell vars win.
load_dotenv(PROJECT_ROOT / ".env", override=False)


# ---------------------------------------------------------------------------
# LLM / runtime config (read from env, with sensible defaults)
# ---------------------------------------------------------------------------

# Which LLM provider to use by default: "anthropic" or "openai"
LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "anthropic").lower()

# Provider-specific default models. Each client reads its own variable; if
# unset, falls back to LLM_MODEL (cross-provider override), then to the
# provider-specific default.
_LLM_MODEL_OVERRIDE = os.environ.get("LLM_MODEL")
DEFAULT_ANTHROPIC_MODEL: str = (
    os.environ.get("ANTHROPIC_MODEL") or _LLM_MODEL_OVERRIDE or "claude-opus-4-7"
)
DEFAULT_OPENAI_MODEL: str = (
    os.environ.get("OPENAI_MODEL") or _LLM_MODEL_OVERRIDE or "gpt-4o"
)

# API keys (None until .env is populated; clients raise with a clear message
# at construction time, not at config import)
ANTHROPIC_API_KEY: str | None = os.environ.get("ANTHROPIC_API_KEY")
OPENAI_API_KEY: str | None = os.environ.get("OPENAI_API_KEY")

# Back-compat alias — older imports use DEFAULT_LLM_MODEL. Resolves to the
# active provider's default.
DEFAULT_LLM_MODEL: str = (
    DEFAULT_OPENAI_MODEL if LLM_PROVIDER == "openai" else DEFAULT_ANTHROPIC_MODEL
)

# Logging level for the RunContext logger
DEFAULT_LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

# Run artifacts root — every pipeline run writes to runs/<run_id>/
RUNS_DIR: Path = PROJECT_ROOT / "runs"

# Prompt templates root — markdown files with {var} placeholders
PROMPTS_DIR: Path = PROJECT_ROOT / "prompts"

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