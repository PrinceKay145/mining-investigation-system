"""
v4 Agents — orchestrator for the four specialist LLM analyses.

Execution model (per DESIGN_DECISIONS.md):
  Phase 1: Agents 1 (Technical), 2 (Organizational), 4 (Regulatory) run in
           parallel — they analyze the raw evidence independently from
           different perspectives.
  Phase 2: Agent 3 (Challenger) runs sequentially after Phase 1 completes,
           receiving the parsed outputs of Agents 1, 2, 4 alongside the raw
           evidence. The Challenger's value is in critiquing specific claims,
           not in producing parallel skepticism.

Each agent call:
  - Loads its prompt via load_prompt() with the case-specific context
  - Calls the LLM with temperature=0.0 (JSON output prefers determinism)
  - Parses the response as a JSON array of Argument objects
  - Logs the event to the RunContext
  - Saves the raw response + parsed arguments as artifacts

Failure handling: if an agent's response is not valid JSON or fails Argument
schema validation, the raw response is persisted to runs/<run_id>/ for
postmortem, and the orchestrator re-raises a ValueError naming the agent.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pydantic import ValidationError

from kb.store import KnowledgeBase
from llm import LLMClient
from llm.logging import RunContext
from prompts import load_prompt
from schema.argument import Argument
from schema.classification import ClassificationResult
from schema.ground_truth import CaseFile
from schema.precedent_match import PrecedentMatchResult
from schema.v4_result import V4Result
from v4_agents.context import (
    extract_canonical_topics,
    format_agent_arguments,
    format_cause_taxonomy,
    format_classification,
    format_evidence_arguments,
    format_investigation_questions,
    format_precedent_matches,
    format_regulatory_requirements,
)

__all__ = ["run_v4", "V4Result", "AgentRunFailure"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AgentRunFailure(RuntimeError):
    """An individual agent failed to produce a valid argument set."""

    def __init__(self, agent_id: str, message: str, raw_response: str | None = None):
        super().__init__(f"{agent_id}: {message}")
        self.agent_id = agent_id
        self.raw_response = raw_response


# ---------------------------------------------------------------------------
# Single-agent runner
# ---------------------------------------------------------------------------

@dataclass
class _AgentSpec:
    agent_id: str            # e.g. "agent_1"
    prompt_name: str         # filename stem under prompts/
    label: str               # human-friendly label for logs


_AGENT_SPECS = {
    "agent_1": _AgentSpec("agent_1", "agent_1_technical", "Technical Causes"),
    "agent_2": _AgentSpec("agent_2", "agent_2_organizational", "Organizational"),
    "agent_3": _AgentSpec("agent_3", "agent_3_challenger", "Challenger"),
    "agent_4": _AgentSpec("agent_4", "agent_4_regulatory", "Regulatory"),
}


def _strip_code_fences(text: str) -> str:
    """If the model wraps its JSON in ```json fences, strip them."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def _parse_agent_response(text: str, agent_id: str) -> list[Argument]:
    """
    Parse a JSON array of Argument objects from the model's response.

    Strips ```json``` fences, validates the result is a JSON array, then
    constructs each Argument (which Pydantic validates).

    Raises:
        AgentRunFailure: on JSON parse failure or schema validation failure.
                         The original raw response is preserved on the exception
                         for persistence by the orchestrator.
    """
    stripped = _strip_code_fences(text)
    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise AgentRunFailure(
            agent_id,
            f"response was not valid JSON: {e}",
            raw_response=text,
        ) from e

    if not isinstance(raw, list):
        raise AgentRunFailure(
            agent_id,
            f"expected JSON array of arguments, got {type(raw).__name__}",
            raw_response=text,
        )

    try:
        return [Argument(**item) for item in raw]
    except ValidationError as e:
        raise AgentRunFailure(
            agent_id,
            f"response did not conform to Argument schema:\n{e}",
            raw_response=text,
        ) from e


def _run_agent(
    *,
    agent_id: str,
    client: LLMClient,
    run: RunContext,
    context_vars: dict,
) -> list[Argument]:
    """
    Render the agent's prompt, call the model, parse the response.

    On failure, persists the raw response to `runs/<run_id>/<agent>_raw.txt`
    before re-raising.
    """
    spec = _AGENT_SPECS[agent_id]
    prompt = load_prompt(spec.prompt_name, **context_vars)

    run.event(f"{agent_id}_start", label=spec.label, prompt_chars=len(prompt))
    result = client.complete(prompt, temperature=0.0)

    # Persist raw response immediately — useful for postmortem on parse failures
    run.save_artifact(f"{agent_id}_raw_response", result.text)

    try:
        arguments = _parse_agent_response(result.text, agent_id)
    except AgentRunFailure as e:
        run.event(
            f"{agent_id}_failed",
            error=str(e),
            response_preview=result.text[:300],
        )
        raise

    run.event(
        f"{agent_id}_done",
        label=spec.label,
        argument_count=len(arguments),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    run.save_artifact(f"{agent_id}_arguments", arguments)
    return arguments


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_v4(
    *,
    case: CaseFile,
    classification: ClassificationResult,
    match_result: PrecedentMatchResult,
    kb: KnowledgeBase,
    client: LLMClient,
    run: RunContext,
) -> V4Result:
    """
    Run the four specialist agents and return their parsed argument sets.

    Sequence:
        1. Build the shared context (formatted strings from v1/v2/v3 outputs
           plus the KB taxonomy and the canonical topic vocabulary extracted
           from the case arguments).
        2. Phase 1 — Agents 1, 2, 4 in parallel via ThreadPoolExecutor.
           Agent 4 receives the additional `regulatory_requirements` context.
        3. Phase 2 — Agent 3 sequentially, receiving the three Phase-1
           outputs serialized into its prompt context.
        4. Save the combined V4Result to `runs/<run_id>/v4_result.json`.

    Raises:
        AgentRunFailure: if any agent fails parsing/validation. The raw
        response is persisted as an artifact regardless.
    """
    run.event("v4_start", case_arguments=len(case.arguments))

    # --- Shared context for all agents ---
    base_context = {
        "investigation_questions": format_investigation_questions(
            case.metadata.investigation_questions
        ),
        "accident_classification": format_classification(
            classification, cause_categories=kb.cause_categories
        ),
        "precedent_matches": format_precedent_matches(match_result, kb.precedents),
        "evidence_arguments": format_evidence_arguments(case.arguments),
        "cause_taxonomy": format_cause_taxonomy(kb.cause_categories),
        "canonical_topics": extract_canonical_topics(case.arguments),
    }

    # Agent 4 needs an extra block
    agent_4_context = {
        **base_context,
        "regulatory_requirements": format_regulatory_requirements(kb.regulations),
    }

    # --- Phase 1: Agents 1, 2, 4 in parallel ---
    run.event("v4_phase1_start", agents=["agent_1", "agent_2", "agent_4"])
    with ThreadPoolExecutor(max_workers=3) as pool:
        f1 = pool.submit(
            _run_agent,
            agent_id="agent_1", client=client, run=run, context_vars=base_context,
        )
        f2 = pool.submit(
            _run_agent,
            agent_id="agent_2", client=client, run=run, context_vars=base_context,
        )
        f4 = pool.submit(
            _run_agent,
            agent_id="agent_4", client=client, run=run, context_vars=agent_4_context,
        )
        a1 = f1.result()
        a2 = f2.result()
        a4 = f4.result()

    # --- Phase 2: Agent 3 sequentially ---
    run.event("v4_phase2_start", agent="agent_3")
    agent_3_context = {
        **base_context,
        "agent_1_arguments": format_agent_arguments(a1),
        "agent_2_arguments": format_agent_arguments(a2),
        "agent_4_arguments": format_agent_arguments(a4),
    }
    a3 = _run_agent(
        agent_id="agent_3", client=client, run=run, context_vars=agent_3_context,
    )

    # --- Persist combined result ---
    result = V4Result(
        agent_1_arguments=a1,
        agent_2_arguments=a2,
        agent_3_arguments=a3,
        agent_4_arguments=a4,
    )
    run.save_artifact("v4_result", result)
    run.event(
        "v4_done",
        agent_1_count=len(a1),
        agent_2_count=len(a2),
        agent_3_count=len(a3),
        agent_4_count=len(a4),
        combined_count=len(result.combined_arguments),
    )

    return result
