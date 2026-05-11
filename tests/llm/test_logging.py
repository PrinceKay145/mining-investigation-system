"""Tests for RunContext — per-run state, JSONL events, artifacts."""

import json
from pathlib import Path

from pydantic import BaseModel

from llm.logging import RunContext


def test_run_context_creates_directory(tmp_path):
    rc = RunContext(name="test", base_dir=tmp_path)
    assert rc.dir.is_dir()
    assert rc.dir.parent == tmp_path
    assert rc.run_id.startswith("test_")


def test_run_id_is_timestamp_based(tmp_path):
    rc1 = RunContext(name="run", base_dir=tmp_path)
    rc2 = RunContext(name="run", base_dir=tmp_path)
    # Different runs get different ids (microsecond precision)
    assert rc1.run_id != rc2.run_id


def test_event_writes_jsonl(tmp_path):
    rc = RunContext(name="test", base_dir=tmp_path)
    rc.event("v1_loaded", arg_count=21, primary_source="kostenko")

    events_path = rc.dir / "events.jsonl"
    assert events_path.is_file()

    line = events_path.read_text().strip()
    record = json.loads(line)
    assert record["event"] == "v1_loaded"
    assert record["arg_count"] == 21
    assert record["primary_source"] == "kostenko"
    assert record["run_id"] == rc.run_id
    assert "timestamp" in record


def test_event_appends_one_line_per_call(tmp_path):
    rc = RunContext(name="test", base_dir=tmp_path)
    rc.event("first")
    rc.event("second", value=42)
    rc.event("third")

    lines = (rc.dir / "events.jsonl").read_text().strip().splitlines()
    assert len(lines) == 3
    events = [json.loads(line)["event"] for line in lines]
    assert events == ["first", "second", "third"]


def test_save_artifact_dict(tmp_path):
    rc = RunContext(name="test", base_dir=tmp_path)
    out = rc.save_artifact("v1_input", {"foo": "bar", "n": 21})
    assert out.suffix == ".json"
    assert out.parent == rc.dir
    assert json.loads(out.read_text()) == {"foo": "bar", "n": 21}


def test_save_artifact_pydantic_model(tmp_path):
    class Sample(BaseModel):
        name: str
        score: float

    rc = RunContext(name="test", base_dir=tmp_path)
    model = Sample(name="kostenko", score=0.91)
    out = rc.save_artifact("classification", model)

    payload = json.loads(out.read_text())
    assert payload == {"name": "kostenko", "score": 0.91}


def test_save_artifact_pydantic_list(tmp_path):
    class Sample(BaseModel):
        id: str

    rc = RunContext(name="test", base_dir=tmp_path)
    out = rc.save_artifact("matches", [Sample(id="a"), Sample(id="b")])
    payload = json.loads(out.read_text())
    assert payload == [{"id": "a"}, {"id": "b"}]


def test_save_artifact_string(tmp_path):
    rc = RunContext(name="test", base_dir=tmp_path)
    out = rc.save_artifact("report", "# Final Report\n\nContent here.")
    assert out.suffix == ".txt"
    assert out.read_text() == "# Final Report\n\nContent here."


def test_event_handles_pydantic_in_kwargs(tmp_path):
    """Pydantic models passed as event kwargs should serialize via _json_default."""
    class Sample(BaseModel):
        primary_type: str

    rc = RunContext(name="test", base_dir=tmp_path)
    rc.event("v2_done", result=Sample(primary_type="methane_explosion"))

    record = json.loads((rc.dir / "events.jsonl").read_text().strip())
    assert record["result"] == {"primary_type": "methane_explosion"}


def test_event_handles_path_and_set_in_kwargs(tmp_path):
    rc = RunContext(name="test", base_dir=tmp_path)
    rc.event("paths", artifact=tmp_path / "x.json", tags={"TC-01", "TC-02"})

    record = json.loads((rc.dir / "events.jsonl").read_text().strip())
    assert record["artifact"] == str(tmp_path / "x.json")
    assert record["tags"] == ["TC-01", "TC-02"]
