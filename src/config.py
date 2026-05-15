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

# ---------------------------------------------------------------------------
# OpenRouter — unified gateway to many free + paid model families.
# Used to assign different model families per v4 agent (methodological
# diversity), and for v5 confirmation / v6 report. See note.md for rationale.
# Model strings should be verified against `GET /api/v1/models` —
# `scripts/ping_openrouter.py --list-free` prints currently-available IDs.
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY: str | None = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL: str = os.environ.get(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
)

OPENROUTER_DEFAULT_MODEL: str = os.environ.get(
    "OPENROUTER_DEFAULT_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
)
OPENROUTER_MODEL_TECHNICAL: str = os.environ.get(
    # Swapped 2026-05-15: free Nemotron-reasoning produced empty content in
    # production (reasoning-token starvation — all 4096 max_tokens consumed by
    # hidden chain-of-thought before any visible answer). Smoke-test of 200
    # tokens missed this. gpt-oss-120b:free is a standard non-reasoning model
    # (no starvation risk), bigger than the dead Nemotron pick, OpenAI RLHF.
    # See runs/kostenko_v6_20260515_002634 for the failure case.
    "OPENROUTER_MODEL_TECHNICAL",
    "openai/gpt-oss-120b:free",
)
OPENROUTER_MODEL_ORGANIZATIONAL: str = os.environ.get(
    # Paid (~$0.63/run) — free Qwen3-Next-80B was blocked by Venice upstream
    # throttling. Same family signature, 3× bigger model, no rate-limit issue.
    "OPENROUTER_MODEL_ORGANIZATIONAL", "qwen/qwen3-235b-a22b-2507"
)
OPENROUTER_MODEL_CHALLENGER: str = os.environ.get(
    # Swapped twice on 2026-05-15:
    #   1. nvidia/nemotron-3-super-120b-a12b:free → markdown prose, no JSON
    #   2. nousresearch/hermes-3-llama-3.1-405b:free → Venice upstream 429
    # Settled on paid Mistral-Small-3.2 (~$0.85/run) — distinct Mistral family
    # signature, direct instruction-following, bypasses the unreliable free pool.
    "OPENROUTER_MODEL_CHALLENGER", "mistralai/mistral-small-3.2-24b-instruct"
)
OPENROUTER_MODEL_REGULATORY: str = os.environ.get(
    # Paid (~$1.24/run) — free Llama-3.3-70B was blocked by Venice upstream
    # throttling. Identical model, bypasses the free-pool quota completely.
    "OPENROUTER_MODEL_REGULATORY", "meta-llama/llama-3.3-70b-instruct"
)
OPENROUTER_MODEL_V5_CONFIRMATION: str = os.environ.get(
    "OPENROUTER_MODEL_V5_CONFIRMATION", "openai/gpt-oss-20b:free"
)
OPENROUTER_MODEL_V6_REPORT: str = os.environ.get(
    # Paid (~$1.24/run) — same Venice-bypass reason as Regulatory.
    "OPENROUTER_MODEL_V6_REPORT", "meta-llama/llama-3.3-70b-instruct"
)
OPENROUTER_MODEL_V1_EXTRACTION: str = os.environ.get(
    "OPENROUTER_MODEL_V1_EXTRACTION", "deepseek/deepseek-v4-flash:free"
)

# Optional OpenRouter attribution headers — used for analytics/leaderboards.
# Not required; left blank by default.
OPENROUTER_HTTP_REFERER: str | None = os.environ.get("OPENROUTER_HTTP_REFERER")
OPENROUTER_X_TITLE: str | None = os.environ.get(
    "OPENROUTER_X_TITLE", "mining-investigation-system"
)

# Back-compat alias — older imports use DEFAULT_LLM_MODEL. Resolves to the
# active provider's default.
def _default_llm_model() -> str:
    if LLM_PROVIDER == "openai":
        return DEFAULT_OPENAI_MODEL
    if LLM_PROVIDER == "openrouter":
        return OPENROUTER_DEFAULT_MODEL
    return DEFAULT_ANTHROPIC_MODEL


DEFAULT_LLM_MODEL: str = _default_llm_model()

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