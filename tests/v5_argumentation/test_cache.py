"""
Tests for v5 pair-check caching.

Cache should:
  - Persist confirmed responses to disk, keyed by content hash.
  - Return cached values without hitting the LLM on a second invocation.
  - Invalidate automatically when argument content changes (different hash).
"""

import json

from llm.logging import RunContext
from schema.argument import Argument
from v5_argumentation.conflict_detection import (
    _cache_get,
    _cache_key,
    _cache_put,
    ConflictDetectionResponse,
    detect_conflicts,
)

from tests.v5_argumentation.test_conflict_detection import FakeClient, _resp


def _arg(arg_id: str, topic: str = "X", claim: str = "claim") -> Argument:
    return Argument(
        id=arg_id, source="X", topic=topic,
        claim=claim, evidence="e", warrant="w",
        confidence=0.5, cause_categories=["TC-01"],
    )


# ---------------------------------------------------------------------------
# _cache_key
# ---------------------------------------------------------------------------

def test_cache_key_is_stable_for_same_content():
    a, b = _arg("A1"), _arg("A2")
    assert _cache_key(a, b, "m1") == _cache_key(a, b, "m1")


def test_cache_key_changes_when_argument_content_changes():
    a, b = _arg("A1", claim="original"), _arg("A2")
    a_modified = _arg("A1", claim="MODIFIED")
    assert _cache_key(a, b, "m1") != _cache_key(a_modified, b, "m1")


def test_cache_key_includes_argument_ids():
    a, b = _arg("A1"), _arg("A2")
    assert _cache_key(a, b, "m1").startswith("A1__A2__")


def test_cache_key_changes_when_model_changes():
    """Different models must produce different cache keys (Axis 4 prep)."""
    a, b = _arg("A1"), _arg("A2")
    assert _cache_key(a, b, "openai/gpt-oss-20b:free") != _cache_key(
        a, b, "google/gemini-2.5-flash-lite"
    )


def test_cache_key_slugifies_model_for_filesystem_safety():
    """Model IDs with `/` and `:` are flattened to `_` so they fit in filenames."""
    a, b = _arg("A1"), _arg("A2")
    key = _cache_key(a, b, "openai/gpt-oss-20b:free")
    # The forward-slash and colon must not appear in the key
    assert "/" not in key
    assert ":" not in key
    # And the slugged form should be embedded
    assert "openai_gpt-oss-20b_free" in key


# ---------------------------------------------------------------------------
# _cache_get / _cache_put
# ---------------------------------------------------------------------------

def test_cache_miss_returns_none(tmp_path):
    assert _cache_get(tmp_path, "nonexistent_key") is None


def test_cache_round_trip(tmp_path):
    response = ConflictDetectionResponse(relation="rebutting", rationale="test")
    _cache_put(tmp_path, "key1", response)
    loaded = _cache_get(tmp_path, "key1")
    assert loaded is not None
    assert loaded.relation == "rebutting"
    assert loaded.rationale == "test"


def test_cache_disabled_when_dir_is_none():
    response = ConflictDetectionResponse(relation="support", rationale="x")
    # Should not raise even though no dir is given
    _cache_put(None, "key", response)
    assert _cache_get(None, "key") is None


def test_cache_corrupt_file_treated_as_miss(tmp_path):
    """Corrupt cache files don't crash — we just re-run the pair."""
    (tmp_path / "bad_key.json").write_text("this is not JSON at all")
    assert _cache_get(tmp_path, "bad_key") is None


# ---------------------------------------------------------------------------
# End-to-end caching via detect_conflicts
# ---------------------------------------------------------------------------

def test_cache_hit_skips_llm_call(tmp_path):
    """Second invocation with same args + cache should make zero LLM calls."""
    args = [_arg("A1"), _arg("A2")]
    cache_dir = tmp_path / "pair_cache"

    # First run: cache populated
    client1 = FakeClient({frozenset({"A1", "A2"}): _resp("rebutting")})
    run1 = RunContext(name="run1", base_dir=tmp_path)
    detect_conflicts(args, client1, run1, cache_dir=cache_dir)
    assert len(client1.calls) == 1

    # Second run with the same args + same cache: cache hit, no LLM call
    client2 = FakeClient({})  # if any call, this raises KeyError
    run2 = RunContext(name="run2", base_dir=tmp_path)
    attacks, supports = detect_conflicts(args, client2, run2, cache_dir=cache_dir)
    assert client2.calls == []
    # Same result as first run
    assert len(attacks) == 2  # rebutting → two directed edges


def test_cache_invalidates_on_content_change(tmp_path):
    """If we change an argument's claim, the cache should miss."""
    cache_dir = tmp_path / "pair_cache"

    args_v1 = [_arg("A1", claim="version_1"), _arg("A2")]
    client1 = FakeClient({frozenset({"A1", "A2"}): _resp("rebutting")})
    detect_conflicts(args_v1, client1, RunContext(name="r1", base_dir=tmp_path),
                     cache_dir=cache_dir)

    # Change A1's content — cache should miss
    args_v2 = [_arg("A1", claim="version_2"), _arg("A2")]
    client2 = FakeClient({frozenset({"A1", "A2"}): _resp("support")})
    detect_conflicts(args_v2, client2, RunContext(name="r2", base_dir=tmp_path),
                     cache_dir=cache_dir)
    assert len(client2.calls) == 1  # cache miss → LLM called


def test_cache_event_logged_on_hit(tmp_path):
    """Cache hits should emit v5_pair_cache_hit events for observability."""
    args = [_arg("A1"), _arg("A2")]
    cache_dir = tmp_path / "pair_cache"

    # Populate cache
    client1 = FakeClient({frozenset({"A1", "A2"}): _resp("support")})
    run1 = RunContext(name="r1", base_dir=tmp_path)
    detect_conflicts(args, client1, run1, cache_dir=cache_dir)

    # Second run — hit
    client2 = FakeClient({})
    run2 = RunContext(name="r2", base_dir=tmp_path)
    detect_conflicts(args, client2, run2, cache_dir=cache_dir)

    events = [json.loads(line) for line in (run2.dir / "events.jsonl").read_text().splitlines()]
    hit_events = [e for e in events if e["event"] == "v5_pair_cache_hit"]
    assert len(hit_events) == 1
    assert hit_events[0]["relation"] == "support"


def test_cache_none_disables_caching(tmp_path):
    """Passing cache_dir=None disables caching: two runs both call the LLM."""
    args = [_arg("A1"), _arg("A2")]

    client1 = FakeClient({frozenset({"A1", "A2"}): _resp("rebutting")})
    detect_conflicts(args, client1, RunContext(name="r1", base_dir=tmp_path),
                     cache_dir=None)
    assert len(client1.calls) == 1

    client2 = FakeClient({frozenset({"A1", "A2"}): _resp("rebutting")})
    detect_conflicts(args, client2, RunContext(name="r2", base_dir=tmp_path),
                     cache_dir=None)
    assert len(client2.calls) == 1  # called again, no cache


def test_cache_namespaces_by_model(tmp_path):
    """
    Axis 4 prep: same args confirmed by model A should NOT return cached
    answers when re-run under model B. Each model gets its own namespace.
    """
    args = [_arg("A1"), _arg("A2")]
    cache_dir = tmp_path / "pair_cache"

    # First confirmation under model A
    client_a = FakeClient(
        {frozenset({"A1", "A2"}): _resp("rebutting")},
        model="openai/gpt-oss-20b:free",
    )
    detect_conflicts(args, client_a, RunContext(name="r1", base_dir=tmp_path),
                     cache_dir=cache_dir)
    assert len(client_a.calls) == 1

    # Re-run with same args + same cache_dir, but DIFFERENT model →
    # should miss the cache and call the new client
    client_b = FakeClient(
        {frozenset({"A1", "A2"}): _resp("support")},  # different answer for B
        model="google/gemini-2.5-flash-lite",
    )
    detect_conflicts(args, client_b, RunContext(name="r2", base_dir=tmp_path),
                     cache_dir=cache_dir)
    assert len(client_b.calls) == 1, "model B should not have hit model A's cache"

    # And running model A AGAIN should hit ITS cache (not model B's)
    client_a_again = FakeClient(
        {},  # would raise KeyError if called
        model="openai/gpt-oss-20b:free",
    )
    detect_conflicts(args, client_a_again, RunContext(name="r3", base_dir=tmp_path),
                     cache_dir=cache_dir)
    assert client_a_again.calls == [], "model A's own cache should still hit"
