# Mining Accident Investigation System

MSc thesis project at NUST MISIS (Data Science). A multi-agent system for automated mining accident investigation — it extends Markarian's classical six-subsystem architecture by replacing the propositional-logic reasoning layers with specialist LLM agents and a formal argumentation framework (Dung's semantics) for conflict resolution.

Primary test case: the Kostenko mine explosion (Kazakhstan, 28 October 2023).

> Work in progress — v1 through v3 are implemented and tested; v4 through v6 are designed but not yet built.

## Architecture

| | Subsystem | What it does | Status |
| --- | --- | --- | --- |
| v1 | Decomposition | Load/extract arguments from expert testimony into a structured form | done |
| v2 | Identification | Rule-based accident-type classification from a cause taxonomy | done |
| v3 | Precedent matching | Two-step CBR — type filter + Jaccard overlap on cause categories | done |
| v4 | Specialist agents | Four LLM agents (Technical, Organizational, Challenger, Regulatory) | pending |
| v5 | Argumentation | Dung's framework — grounded + preferred semantics via NetworkX | pending |
| v6 | Report | LLM-generated explainable investigation report | pending |

Each argument follows a Toulmin-derived 8-field schema: `id, source, topic, claim, evidence, warrant, confidence, cause_categories`. Subsystems 1–3 have intentionally overlapping scope so that v5 has genuine conflicts to resolve.

Full design spec lives in [`system_architecture.json`](system_architecture.json).

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

For v4 onward, set API keys in `.env`:

```dotenv
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
```

## Run

End-to-end demo on the Kostenko case (v1 → v2 → v3):

```bash
python scripts/demo_kostenko.py
```

Tests (90 unit + integration):

```bash
pytest
```

## Knowledge base

- [`data/knowledge_base/kostenko_knowledge_base.json`](data/knowledge_base/kostenko_knowledge_base.json) — 17 expert arguments with ground-truth attack and support relations
- [`data/knowledge_base/rostechnadzor_regulatory_kb_v2.json`](data/knowledge_base/rostechnadzor_regulatory_kb_v2.json) — precedents, regulations, and the cause-category taxonomy

## Stack

Python 3.10+, LangChain / LangGraph, FAISS + SBERT, NetworkX, Pydantic, SQLite.

## Supervisors

- Anna Markarian — Automated Control Systems
- Igor Temkin — Mining Safety and Ecology
