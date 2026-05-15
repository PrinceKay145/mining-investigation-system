"""
Tests for `scripts/build_run_manifest.py`.

Verify the manifest builder correctly aggregates per-role token totals,
counts upstream-429 retries against the right roles, captures stage
timing, and includes the v4 agent_models map.
"""

import json
import sys
from pathlib import Path

# build_run_manifest.py lives under scripts/ — make it importable
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from build_run_manifest import build_manifest  # noqa: E402


def _write_events(tmp_path: Path, events: list[dict]) -> Path:
    """Write a synthetic events.jsonl into a fresh run dir, return the run dir."""
    run_dir = tmp_path / "fake_run"
    run_dir.mkdir()
    (run_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n"
    )
    return run_dir


# ---------------------------------------------------------------------------
# Per-role aggregates
# ---------------------------------------------------------------------------

def test_aggregates_tokens_by_v4_role(tmp_path):
    """v4_start defines role→model; subsequent llm_calls are bucketed by model."""
    events = [
        {"event": "v4_start", "ts": "2026-05-15T00:00:00", "agent_models": {
            "agent_1": "openai/gpt-oss-120b:free",
            "agent_2": "qwen/qwen3-235b-a22b-2507",
            "agent_3": "mistralai/mistral-small-3.2-24b-instruct",
            "agent_4": "meta-llama/llama-3.3-70b-instruct",
        }},
        {"event": "llm_call", "requested_model": "openai/gpt-oss-120b:free",
         "model": "openai/gpt-oss-120b:free", "input_tokens": 3000,
         "output_tokens": 1500, "latency_ms": 4200},
        {"event": "llm_call", "requested_model": "qwen/qwen3-235b-a22b-2507",
         "model": "qwen/qwen3-235b-a22b-2507", "input_tokens": 3500,
         "output_tokens": 1700, "latency_ms": 5100},
        {"event": "llm_call", "requested_model": "openai/gpt-oss-120b:free",
         "model": "openai/gpt-oss-120b:free", "input_tokens": 4000,
         "output_tokens": 1200, "latency_ms": 3800},
    ]
    run_dir = _write_events(tmp_path, events)
    manifest = build_manifest(run_dir)

    # Agent 1 should have 2 calls totaling 7K input
    a1 = manifest["per_role"]["agent_1"]
    assert a1["call_count"] == 2
    assert a1["input_tokens"] == 7000
    assert a1["output_tokens"] == 2700
    assert a1["latency_ms_max"] == 4200

    # Agent 2 should have 1 call
    assert manifest["per_role"]["agent_2"]["call_count"] == 1


def test_upstream_429_retries_attributed_to_throttled_role(tmp_path):
    """A retry event with requested_model X should bump that role's retry_count."""
    events = [
        {"event": "v4_start", "ts": "...", "agent_models": {
            "agent_4": "meta-llama/llama-3.3-70b-instruct:free",
        }},
        {"event": "openrouter_429_retry",
         "requested_model": "meta-llama/llama-3.3-70b-instruct:free",
         "attempt": 1, "sleep_seconds": 29.0},
        {"event": "openrouter_429_retry",
         "requested_model": "meta-llama/llama-3.3-70b-instruct:free",
         "attempt": 2, "sleep_seconds": 30.0},
        {"event": "llm_call",
         "requested_model": "meta-llama/llama-3.3-70b-instruct:free",
         "model": "meta-llama/llama-3.3-70b-instruct:free",
         "input_tokens": 1000, "output_tokens": 500, "latency_ms": 2000},
    ]
    run_dir = _write_events(tmp_path, events)
    manifest = build_manifest(run_dir)
    assert manifest["per_role"]["agent_4"]["retry_count"] == 2
    assert manifest["totals"]["upstream_429_retries"] == 2


def test_non_v4_llm_calls_bucketed_as_other(tmp_path):
    """v5 confirmation / v6 report calls (whose model isn't in v4 map) → 'other'."""
    events = [
        {"event": "v4_start", "ts": "...", "agent_models": {
            "agent_1": "openai/gpt-oss-120b:free",
        }},
        # This call's model isn't in the v4 map — it's a v5/v6 call
        {"event": "llm_call", "requested_model": "openai/gpt-oss-20b:free",
         "model": "openai/gpt-oss-20b:free", "input_tokens": 500,
         "output_tokens": 50, "latency_ms": 800},
    ]
    run_dir = _write_events(tmp_path, events)
    manifest = build_manifest(run_dir)
    assert "other" in manifest["per_role"]
    assert manifest["per_role"]["other"]["call_count"] == 1
    assert manifest["per_role"]["other"]["input_tokens"] == 500


def test_v4_agent_models_captured_in_top_level_field(tmp_path):
    events = [
        {"event": "v4_start", "ts": "...", "agent_models": {
            "agent_1": "openai/gpt-oss-120b:free",
            "agent_2": "qwen/qwen3-235b-a22b-2507",
        }},
    ]
    run_dir = _write_events(tmp_path, events)
    manifest = build_manifest(run_dir)
    assert manifest["v4_agent_models_requested"] == {
        "agent_1": "openai/gpt-oss-120b:free",
        "agent_2": "qwen/qwen3-235b-a22b-2507",
    }


def test_v5_summary_captured_from_v5_done_event(tmp_path):
    events = [
        {"event": "v5_done", "ts": "...",
         "accepted": 26, "rejected": 5, "ambiguous": 12, "consensus": False},
    ]
    run_dir = _write_events(tmp_path, events)
    manifest = build_manifest(run_dir)
    assert manifest["v5_summary"] == {
        "accepted": 26, "rejected": 5, "ambiguous": 12, "consensus": False,
    }


def test_v5_cache_hits_counted(tmp_path):
    events = [
        {"event": "v5_pair_cache_hit", "relation": "support"},
        {"event": "v5_pair_cache_hit", "relation": "rebutting"},
        {"event": "v5_pair_cache_hit", "relation": "support"},
    ]
    run_dir = _write_events(tmp_path, events)
    manifest = build_manifest(run_dir)
    assert manifest["v5_cache_hits"] == 3


def test_totals_aggregate_correctly_across_all_roles(tmp_path):
    events = [
        {"event": "v4_start", "ts": "...", "agent_models": {
            "agent_1": "model-a", "agent_2": "model-b",
        }},
        {"event": "llm_call", "requested_model": "model-a", "model": "model-a",
         "input_tokens": 100, "output_tokens": 50, "latency_ms": 1000},
        {"event": "llm_call", "requested_model": "model-b", "model": "model-b",
         "input_tokens": 200, "output_tokens": 60, "latency_ms": 1100},
        {"event": "llm_call", "requested_model": "model-z", "model": "model-z",
         "input_tokens": 300, "output_tokens": 30, "latency_ms": 700},
    ]
    run_dir = _write_events(tmp_path, events)
    manifest = build_manifest(run_dir)
    assert manifest["totals"]["llm_calls"] == 3
    assert manifest["totals"]["input_tokens"] == 600
    assert manifest["totals"]["output_tokens"] == 140


def test_missing_events_jsonl_raises_with_clear_error(tmp_path):
    import pytest
    empty_dir = tmp_path / "no_events"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="events.jsonl"):
        build_manifest(empty_dir)
