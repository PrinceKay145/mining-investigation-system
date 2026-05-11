"""
Tests for AnthropicClient.

Real API calls are NOT made here — the anthropic.Anthropic class is patched.
This keeps tests fast, free, and independent of network state.
"""

import pytest
from pydantic import BaseModel

from llm.client import AnthropicClient, CompletionResult
from llm.logging import RunContext


# ---------------------------------------------------------------------------
# Fakes — minimal stand-ins for the anthropic SDK objects
# ---------------------------------------------------------------------------

class _FakeContentBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeResponse:
    def __init__(self, text: str, model: str = "claude-opus-4-7"):
        self.content = [_FakeContentBlock(text)]
        self.model = model
        self.usage = _FakeUsage(input_tokens=42, output_tokens=17)
        self.stop_reason = "end_turn"


class _FakeMessages:
    def __init__(self, response_text: str):
        self._text = response_text
        self.last_kwargs: dict | None = None

    def create(self, **kwargs) -> _FakeResponse:
        self.last_kwargs = kwargs
        return _FakeResponse(self._text)


class _FakeAnthropic:
    def __init__(self, response_text: str = "ok"):
        self.messages = _FakeMessages(response_text)


# ---------------------------------------------------------------------------
# Construction / configuration
# ---------------------------------------------------------------------------

def test_client_uses_default_model(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setattr("llm.client.DEFAULT_LLM_MODEL", "claude-opus-4-7")
    client = AnthropicClient(api_key="dummy")
    assert client.model == "claude-opus-4-7"


def test_client_overrides_model_via_constructor():
    client = AnthropicClient(api_key="dummy", model="claude-haiku-4-5-20251001")
    assert client.model == "claude-haiku-4-5-20251001"


def test_client_requires_api_key(monkeypatch):
    monkeypatch.setattr("llm.client.ANTHROPIC_API_KEY", None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicClient()


def test_client_uses_constructor_api_key_over_env(monkeypatch):
    monkeypatch.setattr("llm.client.ANTHROPIC_API_KEY", None)
    # Should not raise — explicit key overrides empty env
    client = AnthropicClient(api_key="explicit-key")
    assert client.model  # construction succeeded


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------

def test_complete_returns_typed_result(monkeypatch):
    fake = _FakeAnthropic(response_text="hello world")
    client = AnthropicClient(api_key="dummy", model="claude-opus-4-7")
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete("Say hi")
    assert isinstance(result, CompletionResult)
    assert result.text == "hello world"
    assert result.model == "claude-opus-4-7"
    assert result.input_tokens == 42
    assert result.output_tokens == 17
    assert result.stop_reason == "end_turn"
    assert result.latency_ms >= 0


def test_complete_passes_system_message(monkeypatch):
    fake = _FakeAnthropic(response_text="ok")
    client = AnthropicClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    client.complete("user prompt", system="you are a test")
    assert fake.messages.last_kwargs["system"] == "you are a test"
    assert fake.messages.last_kwargs["messages"] == [
        {"role": "user", "content": "user prompt"}
    ]


def test_complete_records_event_when_run_context_provided(monkeypatch, tmp_path):
    fake = _FakeAnthropic(response_text="response text")
    rc = RunContext(name="test", base_dir=tmp_path)
    client = AnthropicClient(api_key="dummy", run_context=rc)
    monkeypatch.setattr(client, "_client", fake)

    client.complete("the prompt")

    import json
    events_path = rc.dir / "events.jsonl"
    record = json.loads(events_path.read_text().strip())
    assert record["event"] == "llm_call"
    assert record["input_tokens"] == 42
    assert record["output_tokens"] == 17
    assert record["prompt_preview"] == "the prompt"
    assert record["response_preview"] == "response text"


def test_complete_without_run_context_does_not_log(monkeypatch, tmp_path):
    """A client without a RunContext still works; just no telemetry."""
    fake = _FakeAnthropic(response_text="ok")
    client = AnthropicClient(api_key="dummy")  # no run_context
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete("hi")
    assert result.text == "ok"  # no exception


# ---------------------------------------------------------------------------
# complete_json()
# ---------------------------------------------------------------------------

class _SampleSchema(BaseModel):
    name: str
    score: float


def test_complete_json_parses_valid_response(monkeypatch):
    fake = _FakeAnthropic(response_text='{"name": "kostenko", "score": 0.91}')
    client = AnthropicClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete_json("classify this", schema=_SampleSchema)
    assert isinstance(result, _SampleSchema)
    assert result.name == "kostenko"
    assert result.score == 0.91


def test_complete_json_strips_code_fences(monkeypatch):
    """Models sometimes wrap JSON in ```json ... ``` despite instructions."""
    fenced = '```json\n{"name": "x", "score": 0.5}\n```'
    fake = _FakeAnthropic(response_text=fenced)
    client = AnthropicClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete_json("prompt", schema=_SampleSchema)
    assert result.name == "x"


def test_complete_json_raises_on_malformed(monkeypatch):
    fake = _FakeAnthropic(response_text="this is not JSON at all")
    client = AnthropicClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    with pytest.raises(ValueError, match="did not conform"):
        client.complete_json("prompt", schema=_SampleSchema)


def test_complete_json_uses_low_temperature_by_default(monkeypatch):
    fake = _FakeAnthropic(response_text='{"name": "x", "score": 0.5}')
    client = AnthropicClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    client.complete_json("prompt", schema=_SampleSchema)
    assert fake.messages.last_kwargs["temperature"] == 0.0
