"""
Tests for OpenAIClient.

Real API calls are NOT made — the openai.OpenAI class is replaced with a
fake. This keeps tests fast, free, and independent of network state.
"""

import pytest
from pydantic import BaseModel

from llm.client import CompletionResult
from llm.logging import RunContext
from llm.openai_client import OpenAIClient


# ---------------------------------------------------------------------------
# Fakes — minimal stand-ins for the openai SDK objects
# ---------------------------------------------------------------------------

class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str, finish_reason: str = "stop"):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeUsage:
    def __init__(self, prompt_tokens: int = 42, completion_tokens: int = 17):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeChatResponse:
    def __init__(self, content: str, model: str = "gpt-4o"):
        self.choices = [_FakeChoice(content)]
        self.model = model
        self.usage = _FakeUsage()


class _FakeChatCompletions:
    def __init__(self, response_text: str):
        self._text = response_text
        self.last_kwargs: dict | None = None

    def create(self, **kwargs) -> _FakeChatResponse:
        self.last_kwargs = kwargs
        return _FakeChatResponse(self._text)


class _FakeChat:
    def __init__(self, response_text: str):
        self.completions = _FakeChatCompletions(response_text)


class _FakeOpenAI:
    def __init__(self, response_text: str = "ok"):
        self.chat = _FakeChat(response_text)


# ---------------------------------------------------------------------------
# Construction / configuration
# ---------------------------------------------------------------------------

def test_client_uses_default_model(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr("llm.openai_client.DEFAULT_OPENAI_MODEL", "gpt-4o")
    client = OpenAIClient(api_key="dummy")
    assert client.model == "gpt-4o"


def test_client_overrides_model_via_constructor():
    client = OpenAIClient(api_key="dummy", model="gpt-4o-mini")
    assert client.model == "gpt-4o-mini"


def test_client_requires_api_key(monkeypatch):
    monkeypatch.setattr("llm.openai_client.OPENAI_API_KEY", None)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIClient()


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------

def test_complete_returns_typed_result(monkeypatch):
    fake = _FakeOpenAI(response_text="hello from openai")
    client = OpenAIClient(api_key="dummy", model="gpt-4o")
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete("Say hi")
    assert isinstance(result, CompletionResult)
    assert result.text == "hello from openai"
    assert result.input_tokens == 42
    assert result.output_tokens == 17
    assert result.stop_reason == "stop"
    assert result.latency_ms >= 0


def test_complete_places_system_in_messages_array(monkeypatch):
    """OpenAI uses messages[role=system], not a top-level system param."""
    fake = _FakeOpenAI(response_text="ok")
    client = OpenAIClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    client.complete("user prompt", system="you are a test")
    kwargs = fake.chat.completions.last_kwargs
    assert "system" not in kwargs  # not a top-level field
    assert kwargs["messages"] == [
        {"role": "system", "content": "you are a test"},
        {"role": "user", "content": "user prompt"},
    ]


def test_complete_without_system(monkeypatch):
    fake = _FakeOpenAI(response_text="ok")
    client = OpenAIClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    client.complete("just a user prompt")
    assert fake.chat.completions.last_kwargs["messages"] == [
        {"role": "user", "content": "just a user prompt"},
    ]


def test_complete_records_event_with_provider(monkeypatch, tmp_path):
    fake = _FakeOpenAI(response_text="response text")
    rc = RunContext(name="test", base_dir=tmp_path)
    client = OpenAIClient(api_key="dummy", run_context=rc)
    monkeypatch.setattr(client, "_client", fake)

    client.complete("the prompt")

    import json
    record = json.loads((rc.dir / "events.jsonl").read_text().strip())
    assert record["event"] == "llm_call"
    assert record["provider"] == "openai"
    assert record["prompt_preview"] == "the prompt"


# ---------------------------------------------------------------------------
# complete_json()
# ---------------------------------------------------------------------------

class _Sample(BaseModel):
    name: str
    score: float


def test_complete_json_uses_native_json_mode(monkeypatch):
    """OpenAI's structured output uses response_format={"type":"json_object"}."""
    fake = _FakeOpenAI(response_text='{"name": "x", "score": 0.5}')
    client = OpenAIClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    client.complete_json("classify this", schema=_Sample)
    kwargs = fake.chat.completions.last_kwargs
    assert kwargs["response_format"] == {"type": "json_object"}


def test_complete_json_parses_valid_response(monkeypatch):
    fake = _FakeOpenAI(response_text='{"name": "kostenko", "score": 0.91}')
    client = OpenAIClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete_json("classify", schema=_Sample)
    assert result.name == "kostenko"
    assert result.score == 0.91


def test_complete_json_raises_on_malformed(monkeypatch):
    fake = _FakeOpenAI(response_text="not JSON")
    client = OpenAIClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    with pytest.raises(ValueError, match="did not conform"):
        client.complete_json("prompt", schema=_Sample)
