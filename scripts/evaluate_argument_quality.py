#!/usr/bin/env python
"""
Axis 5 — Score the content quality of every v4-generated argument with
an LLM-as-judge.

The judge scores each argument on four rubric dimensions (1.0–5.0):
  - evidence_groundedness — is the argument's evidence real, or fabricated?
  - warrant_validity     — does the evidence-to-claim reasoning step hold?
  - claim_novelty        — is the argument paraphrase of an existing one?
  - citation_correctness — do cited TC-/OC-/REG- codes resolve to real KB entries?

Then per-agent aggregates are computed in Python (deterministic, not
judged): for each agent 1/2/3/4, the mean per dimension + overall mean.
These per-agent means answer thesis-defining questions:
  - Does the Challenger actually challenge? (Agent 3 novelty mean)
  - Does the Regulatory agent cite real regulations? (Agent 4 citation_correctness mean)
  - Which agent produces the most evidence-grounded arguments?

Uses the user's direct `OPENAI_API_KEY` (not OpenRouter) — judge spend is
structurally isolated from the OpenRouter pipeline budget.

Usage:
    # Most recent v4 run
    python scripts/evaluate_argument_quality.py

    # Specific run + non-default judge model
    python scripts/evaluate_argument_quality.py \\
        --run-dir runs/kostenko_v6_<id> \\
        --judge-model gpt-4o
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import (  # noqa: E402
    DEFAULT_KOSTENKO_KB,
    DEFAULT_REGULATORY_KB,
    RUNS_DIR,
)
from kb.store import KnowledgeBase  # noqa: E402
from llm.openai_client import OpenAIClient  # noqa: E402
from prompts import load_prompt  # noqa: E402
from schema.judge_result import ArgumentQualityResult  # noqa: E402
from v4_agents.context import (  # noqa: E402
    format_cause_taxonomy,
    format_regulatory_requirements,
)


DEFAULT_JUDGE_MODEL = "gpt-4o"

# Map agent ID prefix → human-readable role label (used in per-agent aggregates)
_AGENT_LABELS: dict[str, str] = {
    "agent_1": "Technical",
    "agent_2": "Organizational",
    "agent_3": "Challenger",
    "agent_4": "Regulatory",
}


def section(title: str) -> None:
    bar = "=" * 75
    print(f"\n{bar}\n  {title}\n{bar}")


# ---------------------------------------------------------------------------
# Input formatters
# ---------------------------------------------------------------------------

def format_case_summary(case: dict) -> str:
    """Compact case-file summary the judge uses to check evidence-groundedness."""
    meta = case.get("metadata", {})
    parts = [
        f"- **Case:** {meta.get('case', 'unknown')} "
        f"({meta.get('date', '?')} at {meta.get('location', '?')})",
    ]
    if meta.get("longwall"):
        parts.append(f"- **Longwall:** {meta['longwall']}")
    iqs = meta.get("investigation_questions", [])
    if iqs:
        parts.append("- **Investigation questions:**")
        for q in iqs:
            parts.append(f"  - {q}")
    return "\n".join(parts)


def format_expert_arguments(case: dict) -> str:
    """List expert (v1) arguments — used by the judge to score novelty."""
    lines: list[str] = []
    for a in case.get("arguments", []):
        lines.append(
            f"- `[{a['id']}]` *({a.get('source', '?')})* topic={a.get('topic', '?')}\n"
            f"  - **Claim:** {a.get('claim', '')}\n"
            f"  - **Evidence:** {a.get('evidence', '')}\n"
            f"  - **Cause categories:** {a.get('cause_categories', [])}"
        )
    return "\n".join(lines) if lines else "(no expert arguments in case file)"


def _format_arg_block(arg: dict) -> str:
    """Render one v4 argument as a markdown block with all 8 fields visible."""
    return (
        f"- `[{arg['id']}]` *(source={arg.get('source', '?')}, "
        f"confidence={arg.get('confidence', '?')})* topic={arg.get('topic', '?')}\n"
        f"  - **Claim:** {arg.get('claim', '')}\n"
        f"  - **Evidence:** {arg.get('evidence', '')}\n"
        f"  - **Warrant:** {arg.get('warrant', '')}\n"
        f"  - **Cause categories:** {arg.get('cause_categories', [])}"
    )


def format_v4_arguments(v4: dict) -> str:
    """Group v4 arguments by agent so the judge sees each agent's role context."""
    sections_out: list[str] = []
    for agent_key in (
        "agent_1_arguments", "agent_2_arguments",
        "agent_3_arguments", "agent_4_arguments",
    ):
        args = v4.get(agent_key, [])
        if not args:
            continue
        agent_id = agent_key.replace("_arguments", "")
        label = _AGENT_LABELS.get(agent_id, agent_id)
        sections_out.append(f"### {label} agent ({agent_id}) — {len(args)} arguments")
        for a in args:
            sections_out.append(_format_arg_block(a))
    return "\n\n".join(sections_out)


def build_judge_prompt(*, run_dir: Path, case_path: Path, kb: KnowledgeBase) -> str:
    case = json.loads(case_path.read_text())
    v4 = json.loads((run_dir / "v4_result.json").read_text())
    return load_prompt(
        "judge_argument_quality",
        case_summary=format_case_summary(case),
        cause_taxonomy=format_cause_taxonomy(kb.cause_categories),
        regulation_inventory=format_regulatory_requirements(kb.regulations),
        expert_arguments=format_expert_arguments(case),
        v4_arguments=format_v4_arguments(v4),
    )


# ---------------------------------------------------------------------------
# Per-agent aggregates (computed, not judged)
# ---------------------------------------------------------------------------

def _agent_id_from_arg(arg_id: str) -> str | None:
    """Map an argument ID like 'agent_1_005' to its agent_id ('agent_1')."""
    for prefix in ("agent_1", "agent_2", "agent_3", "agent_4"):
        if arg_id.startswith(prefix + "_"):
            return prefix
    return None


def build_arg_to_agent_map(v4: dict) -> dict[str, str]:
    """
    Canonical arg_id → agent_id lookup built from v4_result.json structure.

    Robust against models that emit non-canonical arg-id prefixes (e.g.
    Gemini 2.5 emitted `analyst_1_001` instead of `agent_1_001` for the
    Technical agent). The v4 result file is the source of truth: each
    `agent_N_arguments` list is owned by `agent_N` regardless of what IDs
    the model wrote into the `id` field.
    """
    mapping: dict[str, str] = {}
    for agent_key in ("agent_1_arguments", "agent_2_arguments",
                      "agent_3_arguments", "agent_4_arguments"):
        agent_id = agent_key.replace("_arguments", "")
        for arg in v4.get(agent_key, []):
            arg_id = arg.get("id")
            if arg_id:
                mapping[arg_id] = agent_id
    return mapping


def compute_per_agent_aggregates(
    result: ArgumentQualityResult,
    arg_to_agent: dict[str, str] | None = None,
) -> dict[str, dict]:
    """
    Per-agent mean scores across the 4 rubric dimensions + overall mean.

    Args:
        result: judge output.
        arg_to_agent: optional canonical arg_id → agent_id lookup (built via
            `build_arg_to_agent_map(v4_result)`). When provided, takes
            precedence over arg-id prefix parsing — required when v4 emitted
            non-canonical IDs. When None, falls back to prefix matching
            (back-compat with callers that only have the judge result).

    Returns:
        Dict keyed by `agent_1`..`agent_4`. Each value has:
            - count: number of scored arguments for this agent
            - mean_evidence_groundedness, mean_warrant_validity,
              mean_claim_novelty, mean_citation_correctness
            - overall_mean: mean of all 4 dimension-means
        Agents with no scored arguments are excluded.
    """
    by_agent: dict[str, list] = {}
    for s in result.scores:
        agent = (arg_to_agent or {}).get(s.arg_id) or _agent_id_from_arg(s.arg_id)
        if agent is None:
            continue
        by_agent.setdefault(agent, []).append(s)

    aggregates: dict[str, dict] = {}
    for agent, scores_list in by_agent.items():
        eg = statistics.mean(s.evidence_groundedness.score for s in scores_list)
        wv = statistics.mean(s.warrant_validity.score for s in scores_list)
        cn = statistics.mean(s.claim_novelty.score for s in scores_list)
        cc = statistics.mean(s.citation_correctness.score for s in scores_list)
        aggregates[agent] = {
            "label": _AGENT_LABELS.get(agent, agent),
            "count": len(scores_list),
            "mean_evidence_groundedness": eg,
            "mean_warrant_validity": wv,
            "mean_claim_novelty": cn,
            "mean_citation_correctness": cc,
            "overall_mean": statistics.mean([eg, wv, cn, cc]),
        }
    return aggregates


# ---------------------------------------------------------------------------
# Output / pretty-printing
# ---------------------------------------------------------------------------

def print_per_argument_scores(result: ArgumentQualityResult) -> None:
    section("Per-argument scores (Axis 5)")
    print()
    print(
        f"  {'arg_id':<18}  {'Evid':>5}  {'Warr':>5}  {'Novl':>5}  "
        f"{'Cite':>5}  {'Mean':>5}"
    )
    print(f"  {'-'*18}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}")
    for s in result.scores:
        print(
            f"  {s.arg_id:<18}  "
            f"{s.evidence_groundedness.score:>5.2f}  "
            f"{s.warrant_validity.score:>5.2f}  "
            f"{s.claim_novelty.score:>5.2f}  "
            f"{s.citation_correctness.score:>5.2f}  "
            f"{s.mean_score:>5.2f}"
        )


def print_per_agent_aggregates(aggregates: dict[str, dict]) -> None:
    section("Per-agent aggregates (Axis 5)")
    print()
    print(
        f"  {'Agent':<22}  {'N':>3}  {'Evid':>5}  {'Warr':>5}  "
        f"{'Novl':>5}  {'Cite':>5}  {'Mean':>5}"
    )
    print(f"  {'-'*22}  {'-'*3}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}")
    for agent in sorted(aggregates.keys()):
        a = aggregates[agent]
        print(
            f"  {a['label']:<22}  {a['count']:>3}  "
            f"{a['mean_evidence_groundedness']:>5.2f}  "
            f"{a['mean_warrant_validity']:>5.2f}  "
            f"{a['mean_claim_novelty']:>5.2f}  "
            f"{a['mean_citation_correctness']:>5.2f}  "
            f"{a['overall_mean']:>5.2f}"
        )
    print()
    print("  Evid = Evidence-groundedness   Warr = Warrant validity")
    print("  Novl = Claim novelty           Cite = Citation correctness")
    print()
    print("  Thesis-defining questions answered by this table:")
    print("    - Does the Challenger actually challenge?  →  Challenger Novl mean")
    print("    - Does the Regulatory agent cite reals?    →  Regulatory Cite mean")
    print("    - Which agent is most evidence-grounded?   →  argmax(Evid mean)")


# ---------------------------------------------------------------------------
# Run-dir discovery
# ---------------------------------------------------------------------------

def find_most_recent_v4_run() -> Path:
    """Most recent runs/<id>/ containing v4_result.json."""
    if not RUNS_DIR.is_dir():
        raise FileNotFoundError(f"No runs directory at {RUNS_DIR}")
    candidates = [
        p for p in RUNS_DIR.iterdir()
        if p.is_dir()
        and not p.name.startswith("_")
        and (p / "v4_result.json").is_file()
    ]
    if not candidates:
        raise FileNotFoundError(f"No runs with v4_result.json under {RUNS_DIR}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir", type=Path, default=None,
        help="Run dir with v4_result.json. Defaults to the most recent.",
    )
    parser.add_argument(
        "--case-file", type=Path, default=DEFAULT_KOSTENKO_KB,
        help="Path to GT case file. Default: kostenko_knowledge_base.json",
    )
    parser.add_argument(
        "--regulatory-kb", type=Path, default=DEFAULT_REGULATORY_KB,
        help="Path to regulatory KB. Default: rostechnadzor_regulatory_kb_v2.json",
    )
    parser.add_argument(
        "--judge-model", type=str, default=DEFAULT_JUDGE_MODEL,
        help=f"OpenAI judge model. Default: {DEFAULT_JUDGE_MODEL}.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Render the prompt to stdout but skip the LLM call.",
    )
    args = parser.parse_args()

    run_dir = args.run_dir or find_most_recent_v4_run()

    section("Argument-quality Judge (Axis 5)")
    print(f"  Run:           {run_dir.name}")
    print(f"  Case file:     {args.case_file}")
    print(f"  Regulatory KB: {args.regulatory_kb}")
    print(f"  Judge model:   {args.judge_model} (via direct OpenAI key)")

    kb = KnowledgeBase.from_files(
        regulatory_path=args.regulatory_kb,
        case_path=args.case_file,
        case_name="kostenko",
    )
    prompt = build_judge_prompt(run_dir=run_dir, case_path=args.case_file, kb=kb)
    print(f"  Prompt size:   {len(prompt):,} chars")

    if args.dry_run:
        print()
        print(prompt)
        return

    # max_tokens=12000: bulk-scoring n=20+ arguments at ~280 output tokens each
    # plus the overall_comments field comfortably fits within this budget.
    # The default 4096 truncated mid-`agent_4_004` on the first real run
    # (2026-05-15 canonical run, 21 args × ~280 tokens ≈ 5,880 tokens needed).
    client = OpenAIClient(model=args.judge_model)
    result = client.complete_json(
        prompt,
        schema=ArgumentQualityResult,
        temperature=0.0,
        max_tokens=12000,
    )

    print_per_argument_scores(result)
    v4_for_map = json.loads((run_dir / "v4_result.json").read_text())
    arg_to_agent = build_arg_to_agent_map(v4_for_map)
    aggregates = compute_per_agent_aggregates(result, arg_to_agent=arg_to_agent)
    print_per_agent_aggregates(aggregates)

    section("Overall comments")
    print()
    print(f"  {result.overall_comments}")

    out_path = run_dir / "judge_argument_quality_result.json"
    payload = result.model_dump()
    for entry in payload.get("scores", []):
        # Add the computed mean so downstream tools don't need to recompute
        scored = next(s for s in result.scores if s.arg_id == entry["arg_id"])
        entry["mean_score"] = scored.mean_score
    payload["per_agent_aggregates"] = aggregates
    payload["judge_model"] = args.judge_model
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print()
    print(f"  Saved: {out_path}")


if __name__ == "__main__":
    main()
