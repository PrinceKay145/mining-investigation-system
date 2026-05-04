"""Tests for the v1 decomposition facade."""

import json

from v1_decomposition import decompose_from_json, decompose_from_text


# ---------------------------------------------------------------------------
# Mode 1 — JSON loader
# ---------------------------------------------------------------------------

def test_decompose_from_json_kostenko(kostenko_kb_path):
    """Loading the real Kostenko KB returns a complete CaseFile."""
    case = decompose_from_json(kostenko_kb_path)
    assert len(case.arguments) == 21
    assert len(case.ground_truth.attack_relations) == 4
    assert len(case.ground_truth.support_relations) == 5
    assert len(case.ground_truth.open_questions) == 5


def test_decompose_from_json_arguments_have_cause_categories(kostenko_kb_path):
    """v1 must reject any input that lacks cause_categories — verify it doesn't."""
    case = decompose_from_json(kostenko_kb_path)
    for arg in case.arguments:
        assert arg.cause_categories, f"{arg.id} has empty cause_categories"


def test_decompose_from_json_missing_file(tmp_path):
    """Nonexistent path should raise FileNotFoundError."""
    missing = tmp_path / "nonexistent.json"
    try:
        decompose_from_json(missing)
        assert False, "Should raise FileNotFoundError"
    except FileNotFoundError:
        pass


def test_decompose_from_json_rejects_missing_categories(tmp_path):
    """A case file with arguments missing cause_categories must be rejected."""
    minimal = {
        "metadata": {"case": "Synthetic", "date": "2026-01-01"},
        "arguments": [
            {
                "id": "X-A1",
                "source": "X",
                "topic": "test",
                "claim": "test claim",
                "evidence": "test evidence",
                "warrant": "test warrant",
                "confidence": 0.5,
            }
        ],
        "argumentation_framework": {
            "attack_relations": [],
            "support_relations": [],
            "open_questions": [],
        },
    }
    path = tmp_path / "no_categories.json"
    with open(path, "w") as f:
        json.dump(minimal, f)

    try:
        decompose_from_json(path)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "cause_categories" in str(e)


# ---------------------------------------------------------------------------
# Mode 2 — LLM extraction (stub)
# ---------------------------------------------------------------------------

def test_decompose_from_text_not_implemented():
    """Mode 2 is deferred — must raise NotImplementedError with a useful pointer."""
    try:
        decompose_from_text("On 2023-10-28 a methane explosion occurred at Kostenko mine...")
        assert False, "Should raise NotImplementedError"
    except NotImplementedError as e:
        # Message should point users at the alternative + the extraction notebook
        msg = str(e)
        assert "decompose_from_json" in msg
        assert "v1_extract_arguments.ipynb" in msg
