"""
Shared test configuration.

Provides:
  1. KB file path fixtures (regulatory_kb_path, kostenko_kb_path)
  2. A synthetic-bad-data fixture for testing referential integrity

Path setup is handled by pyproject.toml's `pythonpath = ["src"]` —
no sys.path manipulation needed.

The cause_categories backfill is no longer a fixture: the Kostenko KB
holds permanent cause_categories as of the 2026-04-27 backfill.
"""

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# KB path fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def regulatory_kb_path() -> Path:
    """Path to the Rostechnadzor regulatory KB (v2)."""
    from config import DEFAULT_REGULATORY_KB
    if not DEFAULT_REGULATORY_KB.exists():
        pytest.skip(f"KB file not found: {DEFAULT_REGULATORY_KB}")
    return DEFAULT_REGULATORY_KB


@pytest.fixture
def kostenko_kb_path() -> Path:
    """Path to the Kostenko case file KB."""
    from config import DEFAULT_KOSTENKO_KB
    if not DEFAULT_KOSTENKO_KB.exists():
        pytest.skip(f"KB file not found: {DEFAULT_KOSTENKO_KB}")
    return DEFAULT_KOSTENKO_KB


# ---------------------------------------------------------------------------
# Synthetic bad-data fixture (for integrity / strict-mode tests)
# ---------------------------------------------------------------------------

@pytest.fixture
def kostenko_with_bad_cause_id(kostenko_kb_path: Path, tmp_path: Path) -> Path:
    """
    Path to a tmp_path copy of Kostenko with U-A1.cause_categories
    set to ['TC-99'] — a category that does not exist in the taxonomy.

    Used to verify the integrity checker catches dangling cause_category
    references and that strict-mode loading rejects them.
    """
    with open(kostenko_kb_path) as f:
        data = json.load(f)
    for arg in data["arguments"]:
        if arg["id"] == "U-A1":
            arg["cause_categories"] = ["TC-99"]
            break
    out = tmp_path / "kostenko_bad.json"
    with open(out, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return out
