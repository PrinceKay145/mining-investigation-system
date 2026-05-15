#!/usr/bin/env python
"""
Axis 2 — Multi-run stability evaluator.

Takes N pipeline runs (same config, same input case file) and reports
**how stable v5's output is under LLM non-determinism**:

  - Pairwise Jaccard between every pair of accepted / rejected / ambiguous
    sets across the N runs. Mean ± std + min / max.
  - Attack-edge stability: pairwise Jaccard on the set of
    `(attacker, target, type)` tuples.
  - Support-cluster stability: pairwise Jaccard on the set of
    frozensets-of-members.
  - Per-argument bucket consistency: of the N runs, how many put a given
    argument in the SAME bucket (accepted / ambiguous / rejected)? An
    argument with `bucket_consistency = N/N` is fully stable; one at 1/N
    or 2/N is a "flipping" argument that varies across runs.

Why this matters for the thesis: cross-model comparisons (Axis 4) are only
defensible if the per-run variance is well-characterized. If accepted-set
Jaccard across 5 same-config runs is, say, 0.92 ± 0.04, then a cross-model
Jaccard of 0.85 is "within sampling noise of the baseline" and not a real
robustness story. Axis 2 establishes the noise floor.

Usage:
    # Last 5 kostenko_* runs (auto-discovery, most common)
    python scripts/evaluate_stability.py --last 5

    # Explicit run dirs (any order)
    python scripts/evaluate_stability.py \\
        --run-dirs runs/r1 runs/r2 runs/r3

Outputs:
  - `stability_report.json` in the *most recent* of the runs (for archival)
  - Console table summary
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from itertools import combinations
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import RUNS_DIR  # noqa: E402


def section(title: str) -> None:
    bar = "=" * 75
    print(f"\n{bar}\n  {title}\n{bar}")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _find_last_n_runs(n: int) -> list[Path]:
    """Return the N most-recent kostenko_* runs that have v5_result.json."""
    candidates = sorted(
        (
            p for p in RUNS_DIR.iterdir()
            if p.is_dir() and p.name.startswith("kostenko_")
            and (p / "v5_result.json").is_file()
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if len(candidates) < n:
        raise FileNotFoundError(
            f"Requested last-{n} kostenko_* runs but only found {len(candidates)} "
            f"under {RUNS_DIR}"
        )
    return candidates[:n]


def _load_v5(run_dir: Path) -> dict:
    return json.loads((run_dir / "v5_result.json").read_text())


# ---------------------------------------------------------------------------
# Jaccard utilities
# ---------------------------------------------------------------------------

def jaccard(a: set, b: set) -> float:
    """Standard Jaccard similarity. Both empty → 1.0 (degenerate identity)."""
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _pairwise_jaccards(sets: list[set]) -> list[float]:
    """All C(N, 2) pairwise Jaccards across a list of N sets."""
    return [jaccard(s1, s2) for s1, s2 in combinations(sets, 2)]


def _stats(values: list[float]) -> dict:
    """Mean, std, min, max for a list of numbers. Empty input → all None."""
    if not values:
        return {"mean": None, "std": None, "min": None, "max": None, "n": 0}
    return {
        "mean": statistics.mean(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
        "n": len(values),
    }


# ---------------------------------------------------------------------------
# Per-aspect stability
# ---------------------------------------------------------------------------

def stability_for_bucket(runs: list[dict], bucket: str) -> dict:
    """
    Pairwise Jaccard for one acceptance bucket ('accepted', 'rejected', 'ambiguous')
    across N runs.
    """
    sets = [set(r.get(bucket, [])) for r in runs]
    jaccs = _pairwise_jaccards(sets)
    return {"bucket": bucket, **_stats(jaccs)}


def stability_for_attacks(runs: list[dict]) -> dict:
    """
    Pairwise Jaccard for the set of attack edges (attacker, target, type)
    across N runs.
    """
    sets: list[set] = []
    for r in runs:
        s = {
            (atk["attacker"], atk["target"], atk["type"])
            for atk in r.get("attack_relations", [])
        }
        sets.append(s)
    return {"aspect": "attack_edges", **_stats(_pairwise_jaccards(sets))}


def stability_for_supports(runs: list[dict]) -> dict:
    """
    Pairwise Jaccard for support clusters across N runs.

    Each cluster is canonicalized to a frozenset of its member IDs so
    member ordering doesn't affect the comparison.
    """
    sets: list[set] = []
    for r in runs:
        s = {
            frozenset(sup.get("supporters", []))
            for sup in r.get("support_relations", [])
        }
        sets.append(s)
    return {"aspect": "support_clusters", **_stats(_pairwise_jaccards(sets))}


def per_argument_bucket_consistency(runs: list[dict]) -> dict:
    """
    For each argument that appears in ANY run, count how many of the N runs
    placed it in the SAME bucket.

    Returns:
        {
            "always_same_bucket": [arg_ids that all N runs agreed on],
            "flipping": [
                {"arg_id": ..., "buckets": {"accepted": k, ...}, "majority": ...},
                ...
            ],
            "summary": {"total": int, "stable": int, "flipping": int,
                        "stability_rate": float}
        }
    """
    from collections import defaultdict

    # arg_id → list of (run_idx, bucket)
    arg_buckets: dict[str, list[str]] = defaultdict(list)
    for r in runs:
        for bucket in ("accepted", "rejected", "ambiguous"):
            for arg_id in r.get(bucket, []):
                arg_buckets[arg_id].append(bucket)

    always_same: list[str] = []
    flipping: list[dict] = []
    for arg_id, buckets in arg_buckets.items():
        unique = set(buckets)
        if len(unique) == 1:
            always_same.append(arg_id)
        else:
            from collections import Counter
            cnts = Counter(buckets)
            majority = cnts.most_common(1)[0][0]
            flipping.append({
                "arg_id": arg_id,
                "buckets": dict(cnts),
                "majority": majority,
                "majority_share": cnts[majority] / len(buckets),
            })

    total = len(arg_buckets)
    stable = len(always_same)
    return {
        "always_same_bucket": sorted(always_same),
        "flipping": sorted(flipping, key=lambda x: -x["majority_share"]),
        "summary": {
            "total_arguments": total,
            "stable_arguments": stable,
            "flipping_arguments": len(flipping),
            "stability_rate": (stable / total) if total else 1.0,
        },
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _fmt_stats(s: dict) -> str:
    if s["mean"] is None:
        return "(n=0, no data)"
    return (
        f"mean={s['mean']:.3f}  std={s['std']:.3f}  "
        f"min={s['min']:.3f}  max={s['max']:.3f}  (n={s['n']} pairs)"
    )


def print_stability_report(report: dict) -> None:
    section(f"Axis 2 — Multi-run stability (N={report['n_runs']})")
    print()
    print("  Runs compared:")
    for r in report["run_ids"]:
        print(f"    - {r}")
    print()
    section("Set-level Jaccard stability")
    print()
    for bucket_stats in report["bucket_stability"]:
        print(f"  {bucket_stats['bucket']:<10}  {_fmt_stats(bucket_stats)}")
    print()
    print(f"  attack_edges        {_fmt_stats(report['attack_stability'])}")
    print(f"  support_clusters    {_fmt_stats(report['support_stability'])}")
    section("Per-argument bucket consistency")
    s = report["per_argument"]["summary"]
    print(
        f"\n  Total arguments seen: {s['total_arguments']}\n"
        f"  Stable (same bucket across all runs):     {s['stable_arguments']:>3}\n"
        f"  Flipping (varies across runs):            {s['flipping_arguments']:>3}\n"
        f"  Stability rate:                           {s['stability_rate']*100:.1f}%"
    )
    flipping = report["per_argument"]["flipping"]
    if flipping:
        print()
        print("  Flipping arguments (sorted by majority share):")
        for f in flipping[:15]:
            buckets_str = ", ".join(
                f"{b}={n}" for b, n in f["buckets"].items()
            )
            print(f"    {f['arg_id']:<20} → majority={f['majority']:<10} "
                  f"(share {f['majority_share']*100:.0f}%)  [{buckets_str}]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--last", type=int, default=None,
        help="Use the most recent N kostenko_* runs that have v5_result.json.",
    )
    parser.add_argument(
        "--run-dirs", nargs="+", type=Path, default=None,
        help="Explicit run dirs to compare. Mutually exclusive with --last.",
    )
    args = parser.parse_args()

    if args.last is not None and args.run_dirs:
        parser.error("Pass --last OR --run-dirs, not both.")
    if args.last is None and not args.run_dirs:
        parser.error("Pass --last N or --run-dirs <dir1> <dir2> ...")

    if args.last is not None:
        run_dirs = _find_last_n_runs(args.last)
    else:
        run_dirs = list(args.run_dirs)

    if len(run_dirs) < 2:
        parser.error(
            f"Stability requires at least 2 runs; got {len(run_dirs)}. "
            "Run the pipeline more times before re-running this script."
        )

    runs = [_load_v5(p) for p in run_dirs]

    report = {
        "n_runs": len(runs),
        "run_ids": [p.name for p in run_dirs],
        "bucket_stability": [
            stability_for_bucket(runs, bucket)
            for bucket in ("accepted", "ambiguous", "rejected")
        ],
        "attack_stability": stability_for_attacks(runs),
        "support_stability": stability_for_supports(runs),
        "per_argument": per_argument_bucket_consistency(runs),
    }

    print_stability_report(report)

    # Save into the most recent run dir for archival
    out_path = run_dirs[0] / "stability_report.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n")
    print()
    print(f"  Saved: {out_path}")


if __name__ == "__main__":
    main()
