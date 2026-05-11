"""Tests for the v6 orchestrator — end-to-end with a mocked LLM client."""

import json

import networkx as nx

from kb.loader import load_case_file, load_regulatory_kb
from kb.store import KnowledgeBase
from llm.client import CompletionResult
from llm.logging import RunContext
from schema.v4_result import V4Result
from schema.v5_result import V5Result
from schema.v6_report import V6ReportContent
from v2_identification import classify
from v3_precedent_matching import match_precedents
from v6_report import run_v6


class FakeV6Client:
    """Returns a canned V6ReportContent JSON for complete_json()."""

    def __init__(self, content: V6ReportContent):
        self._content = content
        self.calls: list[dict] = []

    def complete_json(self, prompt: str, schema, system=None,
                      max_tokens=None, temperature: float = 0.0):
        self.calls.append({"prompt_chars": len(prompt), "temperature": temperature})
        return schema.model_validate_json(self._content.model_dump_json())

    def complete(self, *args, **kwargs) -> CompletionResult:
        raise AssertionError("v6 should not call complete(); use complete_json")


def _sample_content() -> V6ReportContent:
    return V6ReportContent(
        incident_summary="Test incident summary [U-A1].",
        classification_and_precedents="Test classification.",
        accepted_conclusions="Test accepted conclusions.",
        rejected_hypotheses="Test rejected hypotheses.",
        unresolved_questions="Test unresolved questions.",
        regulatory_violations="Test regulatory violations.",
    )


def _setup(regulatory_kb_path, kostenko_kb_path, tmp_path):
    reg_kb = load_regulatory_kb(regulatory_kb_path)
    case = load_case_file(kostenko_kb_path)
    classif = classify(case.arguments, reg_kb.regulations)
    match = match_precedents(classif, reg_kb.precedents)
    kb = KnowledgeBase.from_files(
        regulatory_path=regulatory_kb_path,
        case_path=kostenko_kb_path,
        case_name="kostenko",
    )
    v4 = V4Result()

    # Build a minimal but non-empty v5 result for the graph render
    G = nx.DiGraph()
    G.add_node("U-A1", data={"id": "U-A1"})
    G.add_node("U-A3", data={"id": "U-A3"})
    G.add_edge("U-A1", "U-A3", type="rebutting", attack_id="ATK-V5-001")
    v5 = V5Result(
        af_graph=nx.node_link_data(G, edges="edges"),
        grounded_extension=["U-A1"],
        accepted=["U-A1"],
        rejected=["U-A3"],
    )

    run = RunContext(name="v6test", base_dir=tmp_path)
    return case, classif, match, v4, v5, kb, run


def test_run_v6_returns_v6_report(regulatory_kb_path, kostenko_kb_path, tmp_path):
    case, classif, match, v4, v5, kb, run = _setup(
        regulatory_kb_path, kostenko_kb_path, tmp_path
    )
    client = FakeV6Client(_sample_content())

    report = run_v6(
        case=case, classification=classif, match_result=match,
        v4_result=v4, v5_result=v5, kb=kb, client=client, run=run,
    )

    assert report.case_name == "Kostenko Mine Explosion"
    assert report.run_id == run.run_id
    assert report.counts["expert_arguments"] == 21
    assert report.counts["attacks_detected"] == 0  # v5 had 0 attack_relations
    assert report.counts["accepted"] == 1


def test_run_v6_persists_all_outputs(regulatory_kb_path, kostenko_kb_path, tmp_path):
    case, classif, match, v4, v5, kb, run = _setup(
        regulatory_kb_path, kostenko_kb_path, tmp_path
    )
    client = FakeV6Client(_sample_content())

    run_v6(
        case=case, classification=classif, match_result=match,
        v4_result=v4, v5_result=v5, kb=kb, client=client, run=run,
    )

    assert (run.dir / "v6_report.json").is_file()
    assert (run.dir / "report.md").is_file()
    assert (run.dir / "report.html").is_file()
    assert (run.dir / "argumentation_graph.png").is_file()


def test_run_v6_logs_pipeline_events(regulatory_kb_path, kostenko_kb_path, tmp_path):
    case, classif, match, v4, v5, kb, run = _setup(
        regulatory_kb_path, kostenko_kb_path, tmp_path
    )
    client = FakeV6Client(_sample_content())

    run_v6(
        case=case, classification=classif, match_result=match,
        v4_result=v4, v5_result=v5, kb=kb, client=client, run=run,
    )

    events = [
        json.loads(line)
        for line in (run.dir / "events.jsonl").read_text().splitlines()
    ]
    event_types = {e["event"] for e in events}
    assert {
        "v6_start",
        "v6_graph_rendered",
        "v6_context_built",
        "v6_narrative_done",
        "v6_done",
    }.issubset(event_types)


def test_run_v6_markdown_contains_section_headers(regulatory_kb_path, kostenko_kb_path, tmp_path):
    case, classif, match, v4, v5, kb, run = _setup(
        regulatory_kb_path, kostenko_kb_path, tmp_path
    )
    client = FakeV6Client(_sample_content())

    run_v6(
        case=case, classification=classif, match_result=match,
        v4_result=v4, v5_result=v5, kb=kb, client=client, run=run,
    )

    md = (run.dir / "report.md").read_text()
    for h in ("## 1. Incident summary", "## 7. Regulatory violations"):
        assert h in md


def test_run_v6_uses_relative_graph_path(regulatory_kb_path, kostenko_kb_path, tmp_path):
    """Graph path in the report should be relative so markdown renders from run dir."""
    case, classif, match, v4, v5, kb, run = _setup(
        regulatory_kb_path, kostenko_kb_path, tmp_path
    )
    client = FakeV6Client(_sample_content())
    report = run_v6(
        case=case, classification=classif, match_result=match,
        v4_result=v4, v5_result=v5, kb=kb, client=client, run=run,
    )
    assert report.graph_path == "argumentation_graph.png"  # not an absolute path
