#!/usr/bin/env python
"""
Build `run_manifest.json` from a run's `events.jsonl`.

The manifest is a thesis-friendly summary of what *actually happened* in
one end-to-end run: per-role models (requested vs echoed), token totals,
upstream-429 retry counts, stage timings, and v5/v6 result sizes. Pinning
these into a structured artifact serves three thesis purposes:

  1. Reproducibility — every claim in the thesis evaluation chapter can
     point to a specific run's `run_manifest.json` and recover exactly
     what model produced each subsystem's output.
  2. Cross-model robustness (Axis 4) — compare runs by diffing manifests;
     no rerun, no log-grepping.
  3. Failure-mode taxonomy (Axis 8) — the retry counts and per-role token
     usage surface operational-layer failures that get hidden in averages.

Usage:
    # Most recent run
    python scripts/build_run_manifest.py

    # Specific run
    python scripts/build_run_manifest.py --run-dir runs/kostenko_v6_<id>

Writes `run_manifest.json` into the run directory.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import RUNS_DIR  # noqa: E402


def _load_events(run_dir: Path) -> list[dict]:
    path = run_dir / "events.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"No events.jsonl in {run_dir}")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _agent_id_from_event(e: dict) -> str | None:
    """
    Map an `llm_call` event back to which subsystem role made it.

    Heuristic order:
      1. Explicit `agent_id` field if present.
      2. Match on `requested_model` against the v4 agent_models map captured
         in the `v4_start` event (passed in via `role_to_model`).
    """
    return e.get("agent_id")


def _build_role_to_model(events: list[dict]) -> dict[str, str]:
    """Read the `v4_start` event to recover the per-agent model assignments."""
    for e in events:
        if e.get("event") == "v4_start":
            return dict(e.get("agent_models", {}))
    return {}


def _classify_llm_call(e: dict, role_to_model: dict[str, str]) -> str:
    """Best-effort classification of which subsystem role produced this llm_call."""
    requested = e.get("requested_model")
    # Reverse map: model_string → agent_id
    for agent_id, model in role_to_model.items():
        if model == requested:
            return agent_id
    # If the model matches none of the v4 agents, it's either v5 confirmation
    # or v6 report. We don't have explicit role tagging in the event yet, so
    # we lump them together as "other_llm_calls" — the role-distinguished
    # token totals from v5/v6 are still visible per-event in events.jsonl.
    return "other"


def build_manifest(run_dir: Path) -> dict:
    events = _load_events(run_dir)
    role_to_model = _build_role_to_model(events)

    # --- Per-role aggregates ---
    per_role: dict[str, dict] = defaultdict(
        lambda: {
            "requested_model": None,
            "echoed_models": set(),
            "call_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "latencies_ms": [],
            "retry_count": 0,
        }
    )

    for e in events:
        ev = e.get("event")
        if ev == "llm_call":
            role = _classify_llm_call(e, role_to_model)
            d = per_role[role]
            d["requested_model"] = e.get("requested_model") or d["requested_model"]
            echoed = e.get("model")
            if echoed:
                d["echoed_models"].add(echoed)
            d["call_count"] += 1
            d["input_tokens"] += int(e.get("input_tokens") or 0)
            d["output_tokens"] += int(e.get("output_tokens") or 0)
            lat = e.get("latency_ms")
            if lat is not None:
                d["latencies_ms"].append(int(lat))
        elif ev == "openrouter_429_retry":
            # Map retry back to the role whose model was being throttled
            for agent_id, model in role_to_model.items():
                if model == e.get("requested_model"):
                    per_role[agent_id]["retry_count"] += 1
                    break
            else:
                per_role["other"]["retry_count"] += 1

    # Finalize per-role: turn sets → lists, compute latency stats
    per_role_out: dict[str, dict] = {}
    for role, d in per_role.items():
        latencies = d["latencies_ms"]
        per_role_out[role] = {
            "requested_model": d["requested_model"],
            "echoed_models": sorted(d["echoed_models"]),
            "call_count": d["call_count"],
            "input_tokens": d["input_tokens"],
            "output_tokens": d["output_tokens"],
            "latency_ms_mean": int(statistics.mean(latencies)) if latencies else None,
            "latency_ms_max": max(latencies) if latencies else None,
            "retry_count": d["retry_count"],
        }

    # --- Stage timings (start → done pairs) ---
    stage_timing: dict[str, dict] = {}
    starts: dict[str, str] = {}
    for e in events:
        ev = e.get("event", "")
        ts = e.get("ts") or e.get("timestamp")
        if ev.endswith("_start") and ts:
            stage = ev[: -len("_start")]
            starts[stage] = ts
        elif ev.endswith("_done") and ts:
            stage = ev[: -len("_done")]
            if stage in starts:
                stage_timing[stage] = {
                    "started_at": starts[stage],
                    "finished_at": ts,
                }

    # --- v5 cache stats ---
    v5_cache_hits = sum(1 for e in events if e.get("event") == "v5_pair_cache_hit")

    # --- Final subsystem result sizes ---
    v5_summary = None
    v6_summary = None
    for e in events:
        if e.get("event") == "v5_done":
            v5_summary = {
                "accepted": e.get("accepted"),
                "rejected": e.get("rejected"),
                "ambiguous": e.get("ambiguous"),
                "consensus": e.get("consensus"),
            }
        elif e.get("event") == "v6_done":
            v6_summary = {k: e.get(k) for k in ("event",) if k != "event"}
            v6_summary = dict(e)
            v6_summary.pop("event", None)
            v6_summary.pop("ts", None)
            v6_summary.pop("timestamp", None)

    # --- Totals across all LLM calls ---
    total_input = sum(d["input_tokens"] for d in per_role_out.values())
    total_output = sum(d["output_tokens"] for d in per_role_out.values())
    total_calls = sum(d["call_count"] for d in per_role_out.values())
    total_retries = sum(d["retry_count"] for d in per_role_out.values())

    return {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "v4_agent_models_requested": role_to_model,
        "per_role": per_role_out,
        "stage_timing": stage_timing,
        "v5_cache_hits": v5_cache_hits,
        "v5_summary": v5_summary,
        "v6_summary": v6_summary,
        "totals": {
            "llm_calls": total_calls,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "upstream_429_retries": total_retries,
        },
    }


def find_most_recent_run() -> Path:
    if not RUNS_DIR.is_dir():
        raise FileNotFoundError(f"No runs directory at {RUNS_DIR}")
    candidates = [
        p for p in RUNS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "events.jsonl").is_file()
    ]
    if not candidates:
        raise FileNotFoundError(f"No run dirs with events.jsonl under {RUNS_DIR}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir", type=Path, default=None,
        help="Path to a runs/<id>/ directory. Defaults to the most recent run.",
    )
    parser.add_argument(
        "--stdout", action="store_true",
        help="Print the manifest to stdout instead of writing run_manifest.json.",
    )
    args = parser.parse_args()

    run_dir = args.run_dir or find_most_recent_run()
    manifest = build_manifest(run_dir)
    text = json.dumps(manifest, indent=2, default=str)

    if args.stdout:
        print(text)
    else:
        out = run_dir / "run_manifest.json"
        out.write_text(text + "\n")
        print(f"Wrote {out}")
        print(f"  v4 models: {manifest['v4_agent_models_requested']}")
        print(f"  Totals: {manifest['totals']}")


if __name__ == "__main__":
    main()
