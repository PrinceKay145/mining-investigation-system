#!/usr/bin/env python
"""
Axis 7 — Score a v6 investigation report with an LLM-as-judge.

The judge runs via OpenAI **direct** (the user's `OPENAI_API_KEY`), *not*
via OpenRouter — judge spend is isolated from the OpenRouter pipeline
budget so the cost-of-evaluation is decoupled from the cost-of-generation.
This is methodologically important: the judge must be (a) stronger than
every pipeline model and (b) family-distinct from them. Defaulting to
`gpt-4o` (configurable via `--judge-model`) satisfies both.

Inputs from a run directory:
  - `report.md` — the v6 report to score
  - `v5_result.json` — for attack / support citation verification
  - The case file (default `data/knowledge_base/kostenko_knowledge_base.json`)

Outputs into the same run directory:
  - `judge_v6_report_result.json` — full structured judge output
  - Console summary

Usage:
    # Most recent run
    python scripts/evaluate_v6_report.py

    # Specific run + non-default judge model
    python scripts/evaluate_v6_report.py \\
        --run-dir runs/kostenko_v6_<id> \\
        --judge-model gpt-4o

The script does not call any model in --dry-run mode; instead it prints
the rendered prompt to stdout, which is useful when iterating on the
rubric without burning judge tokens.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import DEFAULT_KOSTENKO_KB, RUNS_DIR  # noqa: E402
from llm.openai_client import OpenAIClient  # noqa: E402
from prompts import load_prompt  # noqa: E402
from schema.judge_result import V6ReportJudgeResult  # noqa: E402


# Default judge model. Must be stronger than every model in the pipeline
# under evaluation; gpt-4o meets that bar for the May-2026 free / Layer-1
# paid pool. Override per-invocation with --judge-model.
DEFAULT_JUDGE_MODEL = "gpt-4o"


def section(title: str) -> None:
    bar = "=" * 75
    print(f"\n{bar}\n  {title}\n{bar}")


# ---------------------------------------------------------------------------
# Input formatters — turn structured artifacts into prompt-friendly markdown
# ---------------------------------------------------------------------------

def format_investigation_questions(questions: list[str]) -> str:
    if not questions:
        return "(none in case file)"
    return "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))


def format_case_summary(case: dict) -> str:
    """Compact GT-fact summary for the judge to check factual claims against."""
    meta = case.get("metadata", {})
    parts = [
        f"- **Case name:** {meta.get('case', 'unknown')}",
        f"- **Date:** {meta.get('date', 'unknown')}",
        f"- **Location:** {meta.get('location', 'unknown')}",
    ]
    longwall = meta.get("longwall")
    if longwall:
        parts.append(f"- **Longwall / section:** {longwall}")
    sources = meta.get("sources", [])
    if sources:
        parts.append("- **Expert sources:**")
        for s in sources:
            if isinstance(s, dict):
                parts.append(
                    f"  - **{s.get('id', '?')}** — {s.get('name', '?')} "
                    f"({s.get('argument_ids_prefix', '?')}*); "
                    f"{s.get('description', '')}"
                )
            else:
                parts.append(f"  - {s}")
    return "\n".join(parts)


def format_argument_inventory(case: dict, v4: dict | None) -> str:
    """List every argument the report could legitimately cite, with ID + 80-char claim."""
    lines = ["### Expert arguments"]
    for a in case.get("arguments", []):
        claim = (a.get("claim") or "")[:80]
        lines.append(f"- `[{a['id']}]` *({a.get('source', '?')})* — {claim}")
    if v4:
        for k in ("agent_1_arguments", "agent_2_arguments",
                  "agent_3_arguments", "agent_4_arguments"):
            args = v4.get(k, [])
            if not args:
                continue
            lines.append(f"\n### {k.replace('_', ' ').title()}")
            for a in args:
                claim = (a.get("claim") or "")[:80]
                lines.append(f"- `[{a['id']}]` — {claim}")
    return "\n".join(lines)


def format_attack_inventory(v5: dict) -> str:
    """List every attack and support the report could legitimately cite."""
    lines = ["### Attacks"]
    for atk in v5.get("attack_relations", []):
        atk_type = atk.get("type") or atk.get("attack_type") or "?"
        lines.append(
            f"- `[{atk['id']}]` — {atk['attacker']} → {atk['target']} ({atk_type})"
        )
    lines.append("\n### Supports")
    for sup in v5.get("support_relations", []):
        members = ", ".join(sup.get("supporters", []))
        lines.append(f"- `[{sup['id']}]` — {{{members}}}  topic: {sup.get('topic', '?')}")
    return "\n".join(lines)


def build_judge_prompt(*, run_dir: Path, case_path: Path) -> str:
    """Render the judge prompt by loading all run artifacts."""
    report_md = (run_dir / "report.md").read_text()
    case = json.loads(case_path.read_text())
    v5 = json.loads((run_dir / "v5_result.json").read_text())
    v4_path = run_dir / "v4_result.json"
    v4 = json.loads(v4_path.read_text()) if v4_path.is_file() else None

    meta = case.get("metadata", {})
    return load_prompt(
        "judge_v6_report",
        case_name=meta.get("case", "unknown"),
        case_date=meta.get("date", "unknown"),
        case_location=meta.get("location", "unknown"),
        investigation_questions=format_investigation_questions(
            meta.get("investigation_questions", [])
        ),
        case_summary=format_case_summary(case),
        argument_inventory=format_argument_inventory(case, v4),
        attack_inventory=format_attack_inventory(v5),
        report_markdown=report_md,
    )


# ---------------------------------------------------------------------------
# Pretty-printer for the judge result
# ---------------------------------------------------------------------------

def print_judge_result(result: V6ReportJudgeResult) -> None:
    section("Axis 7 — v6 Report Judge")
    print()
    for dim_name, dim in [
        ("Factual accuracy",    result.factual_accuracy),
        ("Completeness",        result.completeness),
        ("Citation correctness", result.citation_correctness),
        ("Narrative coherence", result.narrative_coherence),
        ("Defense readiness",   result.defense_readiness),
    ]:
        bar = "█" * int(round(dim.score)) + "·" * (5 - int(round(dim.score)))
        print(f"  {dim_name:<22}  {dim.score:.1f}/5.0  [{bar}]")
        print(f"    └ {dim.rationale}")
        print()

    print(f"  Overall (mean of 5):  {result.overall_score:.2f}/5.0")
    print()
    print(f"  Comments: {result.overall_comments}")
    if result.flagged_issues:
        print()
        print(f"  Flagged issues ({len(result.flagged_issues)}):")
        for i in result.flagged_issues:
            print(f"    - {i}")
    else:
        print()
        print("  Flagged issues: (none — report is filable as-is)")


# ---------------------------------------------------------------------------
# Run-dir discovery
# ---------------------------------------------------------------------------

def find_most_recent_v6_run() -> Path:
    """Most recent runs/<id>/ containing both report.md AND v5_result.json."""
    if not RUNS_DIR.is_dir():
        raise FileNotFoundError(f"No runs directory at {RUNS_DIR}")
    candidates = [
        p for p in RUNS_DIR.iterdir()
        if p.is_dir()
        and not p.name.startswith("_")
        and (p / "report.md").is_file()
        and (p / "v5_result.json").is_file()
    ]
    if not candidates:
        raise FileNotFoundError(
            f"No runs with report.md + v5_result.json under {RUNS_DIR}"
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir", type=Path, default=None,
        help="Path to a run dir with report.md + v5_result.json. "
             "Defaults to the most recent such run.",
    )
    parser.add_argument(
        "--case-file", type=Path, default=DEFAULT_KOSTENKO_KB,
        help="Path to the GT case file. Default: data/knowledge_base/kostenko_knowledge_base.json",
    )
    parser.add_argument(
        "--judge-model", type=str, default=DEFAULT_JUDGE_MODEL,
        help=f"OpenAI judge model. Default: {DEFAULT_JUDGE_MODEL}.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Render the prompt to stdout but skip the LLM call. "
             "Useful for iterating on the rubric.",
    )
    args = parser.parse_args()

    run_dir = args.run_dir or find_most_recent_v6_run()
    section("v6 Report Judge (Axis 7)")
    print(f"  Run:           {run_dir.name}")
    print(f"  Case file:     {args.case_file}")
    print(f"  Judge model:   {args.judge_model} (via direct OpenAI key)")

    prompt = build_judge_prompt(run_dir=run_dir, case_path=args.case_file)
    print(f"  Prompt size:   {len(prompt):,} chars")

    if args.dry_run:
        print()
        print(prompt)
        return

    # Direct OpenAI call (not via OpenRouter) — judge spend lives on the user's
    # OPENAI_API_KEY, isolating it from the OpenRouter pipeline budget.
    client = OpenAIClient(model=args.judge_model)
    result = client.complete_json(
        prompt,
        schema=V6ReportJudgeResult,
        temperature=0.0,
    )
    print_judge_result(result)

    out_path = run_dir / "judge_v6_report_result.json"
    payload = result.model_dump()
    payload["overall_score"] = result.overall_score  # property, included for downstream tools
    payload["judge_model"] = args.judge_model
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print()
    print(f"  Saved: {out_path}")


if __name__ == "__main__":
    main()
