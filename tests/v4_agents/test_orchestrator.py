"""
Tests for the v4 orchestrator.

Real API calls are NOT made — the AnthropicClient is replaced with a fake
whose `complete()` returns scripted JSON responses keyed by which agent
prompt was rendered. This lets us verify orchestration logic (parallel
phase 1, sequential phase 2, context wiring, artifact persistence)
without spending tokens or relying on network state.
"""

import json
from dataclasses import dataclass

import pytest

from kb.loader import load_regulatory_kb, load_case_file
from kb.store import KnowledgeBase
from llm.client import CompletionResult
from llm.logging import RunContext
from v2_identification import classify
from v3_precedent_matching import match_precedents
from v4_agents import build_v4_agent_clients, run_v4, AgentRunFailure


# ---------------------------------------------------------------------------
# Fake LLM client
# ---------------------------------------------------------------------------

class FakeClient:
    """
    Stand-in for AnthropicClient. Returns canned responses keyed by detecting
    which agent's prompt was rendered (each prompt has a unique role line).
    """

    def __init__(self, responses: dict[str, str], model: str = "fake-model"):
        # responses maps agent_id -> JSON string the model "returned"
        self.responses = responses
        self.calls: list[dict] = []  # records each call for assertion
        self.model = model  # LLMClient Protocol requires `.model`

    def complete(self, prompt: str, system=None, max_tokens=None, temperature: float = 1.0) -> CompletionResult:
        # Match on the system-role prefix — unambiguous even when other
        # agents are referenced later in the prompt (e.g. Agent 3 quotes
        # Agents 1/2/4 outputs by name in its review section)
        if "You are an **Independent Challenger**" in prompt:
            agent = "agent_3"
        elif "You are a **Technical Causes Analyst**" in prompt:
            agent = "agent_1"
        elif "You are an **Organizational and Human Factors Analyst**" in prompt:
            agent = "agent_2"
        elif "You are a **Regulatory Compliance Checker**" in prompt:
            agent = "agent_4"
        else:
            raise AssertionError(f"Could not identify agent from prompt: {prompt[:200]}")

        self.calls.append({"agent": agent, "prompt": prompt, "temperature": temperature})
        return CompletionResult(
            text=self.responses[agent],
            model="fake-model",
            input_tokens=100,
            output_tokens=50,
            latency_ms=10,
            stop_reason="end_turn",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(agent_id: str, n: int = 2) -> str:
    """Make a JSON array of n minimal valid Arguments tagged as the agent."""
    args = [
        {
            "id": f"{agent_id}_{i:03d}",
            "source": agent_id,
            "topic": "Ignition source",
            "claim": f"claim from {agent_id} #{i}",
            "evidence": "supporting evidence",
            "warrant": "reasoning",
            "confidence": 0.7,
            "cause_categories": ["TC-02"],
        }
        for i in range(1, n + 1)
    ]
    return json.dumps(args)


@pytest.fixture
def setup(regulatory_kb_path, kostenko_kb_path, tmp_path):
    """Bundle the inputs the orchestrator needs into a single fixture."""
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    classification = classify(case.arguments, reg_kb.regulations)
    match_result = match_precedents(classification, reg_kb.precedents)
    kb = KnowledgeBase.from_files(regulatory_path=regulatory_kb_path,
                                  case_path=kostenko_kb_path,
                                  case_name="kostenko")
    run = RunContext(name="v4test", base_dir=tmp_path)

    @dataclass
    class Setup:
        case: object
        classification: object
        match_result: object
        kb: object
        run: object
    return Setup(case=case, classification=classification,
                 match_result=match_result, kb=kb, run=run)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_run_v4_calls_all_four_agents(setup):
    client = FakeClient({
        "agent_1": _make_response("agent_1"),
        "agent_2": _make_response("agent_2"),
        "agent_3": _make_response("agent_3"),
        "agent_4": _make_response("agent_4"),
    })
    result = run_v4(
        case=setup.case, classification=setup.classification,
        match_result=setup.match_result, kb=setup.kb,
        client=client, run=setup.run,
    )

    called = [c["agent"] for c in client.calls]
    assert set(called) == {"agent_1", "agent_2", "agent_3", "agent_4"}
    assert len(client.calls) == 4
    assert len(result.combined_arguments) == 8  # 2 args × 4 agents


def test_run_v4_agent_3_runs_after_phase_1(setup):
    """Phase 2 must follow Phase 1 — Agent 3's call is last in the sequence."""
    client = FakeClient({
        "agent_1": _make_response("agent_1"),
        "agent_2": _make_response("agent_2"),
        "agent_3": _make_response("agent_3"),
        "agent_4": _make_response("agent_4"),
    })
    run_v4(
        case=setup.case, classification=setup.classification,
        match_result=setup.match_result, kb=setup.kb,
        client=client, run=setup.run,
    )
    called_order = [c["agent"] for c in client.calls]
    # Agent 3 must come after agents 1, 2, 4 — those three appear in any order
    a3_idx = called_order.index("agent_3")
    for other in ("agent_1", "agent_2", "agent_4"):
        assert called_order.index(other) < a3_idx


def test_run_v4_injects_phase_1_outputs_into_agent_3(setup):
    """Agent 3's prompt should contain the JSON output of agents 1, 2, 4."""
    client = FakeClient({
        "agent_1": _make_response("agent_1"),
        "agent_2": _make_response("agent_2"),
        "agent_3": _make_response("agent_3"),
        "agent_4": _make_response("agent_4"),
    })
    run_v4(
        case=setup.case, classification=setup.classification,
        match_result=setup.match_result, kb=setup.kb,
        client=client, run=setup.run,
    )
    a3_call = next(c for c in client.calls if c["agent"] == "agent_3")
    assert "agent_1_001" in a3_call["prompt"]
    assert "agent_2_001" in a3_call["prompt"]
    assert "agent_4_001" in a3_call["prompt"]


def test_run_v4_uses_temperature_zero_for_json(setup):
    """All agent calls must use temperature 0.0 (determinism for JSON outputs)."""
    client = FakeClient({
        "agent_1": _make_response("agent_1"),
        "agent_2": _make_response("agent_2"),
        "agent_3": _make_response("agent_3"),
        "agent_4": _make_response("agent_4"),
    })
    run_v4(
        case=setup.case, classification=setup.classification,
        match_result=setup.match_result, kb=setup.kb,
        client=client, run=setup.run,
    )
    for c in client.calls:
        assert c["temperature"] == 0.0


def test_run_v4_canonical_topics_injected_into_phase_1_prompts(setup):
    """The Kostenko canonical topics should appear in Agents 1, 2, 4 prompts."""
    client = FakeClient({
        "agent_1": _make_response("agent_1"),
        "agent_2": _make_response("agent_2"),
        "agent_3": _make_response("agent_3"),
        "agent_4": _make_response("agent_4"),
    })
    run_v4(
        case=setup.case, classification=setup.classification,
        match_result=setup.match_result, kb=setup.kb,
        client=client, run=setup.run,
    )
    for agent_id in ("agent_1", "agent_2", "agent_4"):
        call = next(c for c in client.calls if c["agent"] == agent_id)
        assert "Ignition source" in call["prompt"]
        assert "Methane source" in call["prompt"]
        assert "Ventilation" in call["prompt"]


# ---------------------------------------------------------------------------
# Artifact persistence
# ---------------------------------------------------------------------------

def test_run_v4_persists_each_agent_response(setup):
    client = FakeClient({
        "agent_1": _make_response("agent_1"),
        "agent_2": _make_response("agent_2"),
        "agent_3": _make_response("agent_3"),
        "agent_4": _make_response("agent_4"),
    })
    run_v4(
        case=setup.case, classification=setup.classification,
        match_result=setup.match_result, kb=setup.kb,
        client=client, run=setup.run,
    )
    for agent_id in ("agent_1", "agent_2", "agent_3", "agent_4"):
        assert (setup.run.dir / f"{agent_id}_raw_response.txt").is_file()
        assert (setup.run.dir / f"{agent_id}_arguments.json").is_file()


def test_run_v4_persists_combined_result(setup):
    client = FakeClient({
        "agent_1": _make_response("agent_1"),
        "agent_2": _make_response("agent_2"),
        "agent_3": _make_response("agent_3"),
        "agent_4": _make_response("agent_4"),
    })
    run_v4(
        case=setup.case, classification=setup.classification,
        match_result=setup.match_result, kb=setup.kb,
        client=client, run=setup.run,
    )
    v4_path = setup.run.dir / "v4_result.json"
    assert v4_path.is_file()
    data = json.loads(v4_path.read_text())
    assert len(data["agent_1_arguments"]) == 2
    assert len(data["agent_2_arguments"]) == 2
    assert len(data["agent_3_arguments"]) == 2
    assert len(data["agent_4_arguments"]) == 2


def test_run_v4_logs_events(setup):
    client = FakeClient({
        "agent_1": _make_response("agent_1"),
        "agent_2": _make_response("agent_2"),
        "agent_3": _make_response("agent_3"),
        "agent_4": _make_response("agent_4"),
    })
    run_v4(
        case=setup.case, classification=setup.classification,
        match_result=setup.match_result, kb=setup.kb,
        client=client, run=setup.run,
    )
    events_file = setup.run.dir / "events.jsonl"
    events = [json.loads(line) for line in events_file.read_text().splitlines()]
    event_types = {e["event"] for e in events}
    assert "v4_start" in event_types
    assert "v4_phase1_start" in event_types
    assert "v4_phase2_start" in event_types
    assert "v4_done" in event_types
    # Every agent should log start + done
    for agent_id in ("agent_1", "agent_2", "agent_3", "agent_4"):
        assert f"{agent_id}_start" in event_types
        assert f"{agent_id}_done" in event_types


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------

def test_run_v4_raises_on_malformed_json(setup):
    """Non-JSON agent response → AgentRunFailure with the raw text preserved."""
    client = FakeClient({
        "agent_1": "this is not JSON",
        "agent_2": _make_response("agent_2"),
        "agent_3": _make_response("agent_3"),
        "agent_4": _make_response("agent_4"),
    })
    with pytest.raises(AgentRunFailure) as exc_info:
        run_v4(
            case=setup.case, classification=setup.classification,
            match_result=setup.match_result, kb=setup.kb,
            client=client, run=setup.run,
        )
    assert exc_info.value.agent_id == "agent_1"
    assert exc_info.value.raw_response == "this is not JSON"
    # Raw response should still be persisted
    assert (setup.run.dir / "agent_1_raw_response.txt").is_file()


def test_run_v4_raises_on_schema_violation(setup):
    """JSON parses but doesn't match Argument schema → AgentRunFailure."""
    bad = json.dumps([{"id": "x"}])  # missing required fields
    client = FakeClient({
        "agent_1": bad,
        "agent_2": _make_response("agent_2"),
        "agent_3": _make_response("agent_3"),
        "agent_4": _make_response("agent_4"),
    })
    with pytest.raises(AgentRunFailure) as exc_info:
        run_v4(
            case=setup.case, classification=setup.classification,
            match_result=setup.match_result, kb=setup.kb,
            client=client, run=setup.run,
        )
    assert exc_info.value.agent_id == "agent_1"
    assert "Argument schema" in str(exc_info.value)


def test_run_v4_strips_code_fences(setup):
    """Responses wrapped in ```json fences should still parse."""
    fenced = "```json\n" + _make_response("agent_1") + "\n```"
    client = FakeClient({
        "agent_1": fenced,
        "agent_2": _make_response("agent_2"),
        "agent_3": _make_response("agent_3"),
        "agent_4": _make_response("agent_4"),
    })
    result = run_v4(
        case=setup.case, classification=setup.classification,
        match_result=setup.match_result, kb=setup.kb,
        client=client, run=setup.run,
    )
    assert len(result.agent_1_arguments) == 2


# ---------------------------------------------------------------------------
# Per-agent client injection (clients= API)
# ---------------------------------------------------------------------------

def _make_four_fake_clients_by_agent() -> dict[str, FakeClient]:
    """Build four distinct FakeClient instances, each tagged with its own model."""
    return {
        agent_id: FakeClient(
            responses={agent_id: _make_response(agent_id)},
            model=f"{agent_id}-model",
        )
        for agent_id in ("agent_1", "agent_2", "agent_3", "agent_4")
    }


def test_run_v4_clients_dict_routes_each_agent_to_its_own_client(setup):
    """With clients=, each agent must call its own dedicated client (and only that one)."""
    clients = _make_four_fake_clients_by_agent()
    run_v4(
        case=setup.case, classification=setup.classification,
        match_result=setup.match_result, kb=setup.kb,
        clients=clients, run=setup.run,
    )
    # Each per-agent fake should have been called exactly once, with its own agent_id
    for agent_id, fake in clients.items():
        assert len(fake.calls) == 1, f"{agent_id} client should be called exactly once"
        assert fake.calls[0]["agent"] == agent_id


def test_run_v4_logs_agent_models_in_v4_start_event(setup):
    """v4_start event records each agent's model, supporting cross-model-robustness Axis 4."""
    clients = _make_four_fake_clients_by_agent()
    run_v4(
        case=setup.case, classification=setup.classification,
        match_result=setup.match_result, kb=setup.kb,
        clients=clients, run=setup.run,
    )
    import json
    events = [
        json.loads(line) for line in (setup.run.dir / "events.jsonl").read_text().splitlines()
    ]
    v4_start = next(e for e in events if e["event"] == "v4_start")
    assert v4_start["agent_models"] == {
        "agent_1": "agent_1-model",
        "agent_2": "agent_2-model",
        "agent_3": "agent_3-model",
        "agent_4": "agent_4-model",
    }


def test_run_v4_rejects_passing_both_client_and_clients(setup):
    fake = FakeClient({a: _make_response(a) for a in ("agent_1", "agent_2", "agent_3", "agent_4")})
    clients = _make_four_fake_clients_by_agent()
    with pytest.raises(ValueError, match="exactly one"):
        run_v4(
            case=setup.case, classification=setup.classification,
            match_result=setup.match_result, kb=setup.kb,
            client=fake, clients=clients, run=setup.run,
        )


def test_run_v4_rejects_passing_neither_client_nor_clients(setup):
    with pytest.raises(ValueError, match="exactly one"):
        run_v4(
            case=setup.case, classification=setup.classification,
            match_result=setup.match_result, kb=setup.kb,
            run=setup.run,
        )


def test_run_v4_rejects_clients_dict_missing_agent_key(setup):
    clients = _make_four_fake_clients_by_agent()
    del clients["agent_3"]
    with pytest.raises(ValueError, match="missing entries"):
        run_v4(
            case=setup.case, classification=setup.classification,
            match_result=setup.match_result, kb=setup.kb,
            clients=clients, run=setup.run,
        )


# ---------------------------------------------------------------------------
# build_v4_agent_clients factory
# ---------------------------------------------------------------------------

def test_build_v4_agent_clients_shares_one_client_for_anthropic(monkeypatch):
    monkeypatch.setattr("v4_agents.LLM_PROVIDER", "anthropic")
    monkeypatch.setattr("llm.client.ANTHROPIC_API_KEY", "dummy")
    clients = build_v4_agent_clients()
    # Single shared client → all four references point at the same instance
    distinct_instances = {id(c) for c in clients.values()}
    assert len(distinct_instances) == 1
    assert set(clients.keys()) == {"agent_1", "agent_2", "agent_3", "agent_4"}


def test_build_v4_agent_clients_one_per_agent_for_openrouter(monkeypatch):
    """Under LLM_PROVIDER=openrouter, each agent gets its own client with its role's model."""
    monkeypatch.setattr("v4_agents.LLM_PROVIDER", "openrouter")
    monkeypatch.setattr("llm.openrouter_client.OPENROUTER_API_KEY", "dummy")
    monkeypatch.setattr("v4_agents.OPENROUTER_MODEL_TECHNICAL", "model-tech")
    monkeypatch.setattr("v4_agents.OPENROUTER_MODEL_ORGANIZATIONAL", "model-org")
    monkeypatch.setattr("v4_agents.OPENROUTER_MODEL_CHALLENGER", "model-chal")
    monkeypatch.setattr("v4_agents.OPENROUTER_MODEL_REGULATORY", "model-reg")

    clients = build_v4_agent_clients()

    # Four distinct instances
    distinct_instances = {id(c) for c in clients.values()}
    assert len(distinct_instances) == 4
    # Each agent got its role-specific model
    assert clients["agent_1"].model == "model-tech"
    assert clients["agent_2"].model == "model-org"
    assert clients["agent_3"].model == "model-chal"
    assert clients["agent_4"].model == "model-reg"
