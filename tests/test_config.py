"""Tests for config — verify paths resolve and constants are sane."""

import re
from config import (
    PROJECT_ROOT,
    CAUSE_CATEGORY_PATTERN,
    REGULATION_PATTERN,
    SIMILARITY_BOOL_FLAGS,
)
from schema.precedent import SimilarityProfile


def test_project_root_is_directory():
    assert PROJECT_ROOT.is_dir()


def test_project_root_contains_src():
    assert (PROJECT_ROOT / "src").is_dir()


def test_cause_category_pattern():
    p = re.compile(CAUSE_CATEGORY_PATTERN)
    assert p.match("TC-01")
    assert p.match("OC-10")
    assert not p.match("XX-01")
    assert not p.match("TC01")


def test_regulation_pattern():
    p = re.compile(REGULATION_PATTERN)
    assert p.match("REG-01")
    assert p.match("REG-14")
    assert not p.match("REG01")


def test_similarity_bool_flags_count():
    assert len(SIMILARITY_BOOL_FLAGS) == 20


def test_similarity_flags_are_valid_field_names():
    model_fields = set(SimilarityProfile.model_fields.keys())
    for flag in SIMILARITY_BOOL_FLAGS:
        assert flag in model_fields, f"'{flag}' not a SimilarityProfile field"
