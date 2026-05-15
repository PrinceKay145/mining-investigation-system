"""
Tests for OpenRouterClient.

Real API calls are NOT made — the openai.OpenAI class is replaced with a
fake. This keeps tests fast, free, and independent of network state.

The OpenRouter-specific behavior under test:
  - Construction reads OPENROUTER_API_KEY (not OPENAI_API_KEY).
  - The OpenAI SDK is initialized with base_url=https://openrouter.ai/api/v1.
  - complete_json's two-attempt fallback: if the first attempt (with
    response_format=json_object) returns empty / malformed text, the client
    retries without response_format and with a stricter prompt.
"""

import pytest
from pydantic import BaseModel

from llm.client import CompletionResult
from llm.logging import RunContext
from llm.openrouter_client import OpenRouterClient


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
    def __init__(self, content: str, model: str = "deepseek/deepseek-r1:free"):
        self.choices = [_FakeChoice(content)]
        self.model = model
        self.usage = _FakeUsage()


class _FakeChatCompletions:
    """
    Programmable fake. Construct with a list of response texts; each .create()
    call pops the next one. Records every call's kwargs in `calls`.
    """

    def __init__(self, response_texts: list[str]):
        self._responses = list(response_texts)
        self.calls: list[dict] = []

    def create(self, **kwargs) -> _FakeChatResponse:
        self.calls.append(kwargs)
        text = self._responses.pop(0) if self._responses else ""
        return _FakeChatResponse(text)


class _FakeChat:
    def __init__(self, response_texts: list[str]):
        self.completions = _FakeChatCompletions(response_texts)


class _FakeOpenAI:
    """Fake openai.OpenAI surface."""

    def __init__(self, response_texts: list[str] | str = "ok"):
        if isinstance(response_texts, str):
            response_texts = [response_texts]
        self.chat = _FakeChat(response_texts)


# ---------------------------------------------------------------------------
# Construction / configuration
# ---------------------------------------------------------------------------

def test_client_uses_default_model(monkeypatch):
    monkeypatch.delenv("OPENROUTER_DEFAULT_MODEL", raising=False)
    monkeypatch.setattr(
        "llm.openrouter_client.OPENROUTER_DEFAULT_MODEL",
        "meta-llama/llama-3.3-70b-instruct:free",
    )
    client = OpenRouterClient(api_key="dummy")
    assert client.model == "meta-llama/llama-3.3-70b-instruct:free"


def test_client_overrides_model_via_constructor():
    client = OpenRouterClient(api_key="dummy", model="deepseek/deepseek-r1:free")
    assert client.model == "deepseek/deepseek-r1:free"


def test_client_requires_api_key(monkeypatch):
    monkeypatch.setattr("llm.openrouter_client.OPENROUTER_API_KEY", None)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterClient()


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------

def test_complete_returns_typed_result(monkeypatch):
    fake = _FakeOpenAI(response_texts="hello from openrouter")
    client = OpenRouterClient(api_key="dummy", model="deepseek/deepseek-r1:free")
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete("Say hi")
    assert isinstance(result, CompletionResult)
    assert result.text == "hello from openrouter"
    assert result.input_tokens == 42
    assert result.output_tokens == 17
    assert result.stop_reason == "stop"
    assert result.latency_ms >= 0


def test_complete_records_event_with_openrouter_provider(monkeypatch, tmp_path):
    fake = _FakeOpenAI(response_texts="response text")
    rc = RunContext(name="test", base_dir=tmp_path)
    client = OpenRouterClient(
        api_key="dummy",
        model="deepseek/deepseek-r1:free",
        run_context=rc,
    )
    monkeypatch.setattr(client, "_client", fake)

    client.complete("the prompt")

    import json
    record = json.loads((rc.dir / "events.jsonl").read_text().strip())
    assert record["event"] == "llm_call"
    assert record["provider"] == "openrouter"
    assert record["requested_model"] == "deepseek/deepseek-r1:free"
    assert record["prompt_preview"] == "the prompt"


# ---------------------------------------------------------------------------
# complete_json() — happy path
# ---------------------------------------------------------------------------

class _Sample(BaseModel):
    name: str
    score: float


def test_complete_json_first_attempt_uses_response_format(monkeypatch):
    fake = _FakeOpenAI(response_texts='{"name": "x", "score": 0.5}')
    client = OpenRouterClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    client.complete_json("classify this", schema=_Sample)
    first_call = fake.chat.completions.calls[0]
    assert first_call["response_format"] == {"type": "json_object"}


def test_complete_json_parses_valid_first_attempt(monkeypatch):
    fake = _FakeOpenAI(response_texts='{"name": "kostenko", "score": 0.91}')
    client = OpenRouterClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete_json("classify", schema=_Sample)
    assert result.name == "kostenko"
    assert result.score == 0.91
    # Only one chat call required
    assert len(fake.chat.completions.calls) == 1


# ---------------------------------------------------------------------------
# complete_json() — fallback behavior
# ---------------------------------------------------------------------------

def test_complete_json_fallback_on_empty_first_response(monkeypatch):
    """
    Simulates DeepSeek R1's empty-content failure mode: first call with
    response_format returns empty; second call (no response_format, stricter
    prompt) returns valid JSON.
    """
    fake = _FakeOpenAI(response_texts=["", '{"name": "ok", "score": 1.0}'])
    client = OpenRouterClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete_json("prompt", schema=_Sample)
    assert result.name == "ok"
    assert result.score == 1.0

    # Two calls were made
    assert len(fake.chat.completions.calls) == 2
    # First used response_format; second did not
    assert fake.chat.completions.calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in fake.chat.completions.calls[1]


def test_complete_json_fallback_on_unparseable_first_response(monkeypatch):
    """First response is non-JSON prose (R1 leaks reasoning); fallback rescues it."""
    fake = _FakeOpenAI(
        response_texts=[
            "Let me think... the answer is name=ok and score=1.0",
            '{"name": "ok", "score": 1.0}',
        ]
    )
    client = OpenRouterClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete_json("prompt", schema=_Sample)
    assert result.name == "ok"
    assert len(fake.chat.completions.calls) == 2


def test_complete_json_strips_code_fences(monkeypatch):
    """Model wraps JSON in ```json fences despite instructions; client strips them."""
    fake = _FakeOpenAI(
        response_texts=['```json\n{"name": "x", "score": 0.5}\n```']
    )
    client = OpenRouterClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete_json("prompt", schema=_Sample)
    assert result.name == "x"
    # Only one call — fence-stripping succeeded on attempt 1
    assert len(fake.chat.completions.calls) == 1


def test_complete_json_raises_after_both_attempts_fail(monkeypatch):
    """Both attempts return junk; client raises with both raw responses in message."""
    fake = _FakeOpenAI(response_texts=["junk one", "junk two"])
    client = OpenRouterClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    with pytest.raises(ValueError, match="after 2 attempts"):
        client.complete_json("prompt", schema=_Sample)
    assert len(fake.chat.completions.calls) == 2


def test_complete_json_records_fallback_in_telemetry(monkeypatch, tmp_path):
    fake = _FakeOpenAI(response_texts=["", '{"name": "ok", "score": 1.0}'])
    rc = RunContext(name="test", base_dir=tmp_path)
    client = OpenRouterClient(api_key="dummy", run_context=rc)
    monkeypatch.setattr(client, "_client", fake)

    client.complete_json("prompt", schema=_Sample)

    import json
    record = json.loads((rc.dir / "events.jsonl").read_text().strip())
    assert record["used_fallback"] is True
    assert record["response_format"] == "prompt-only"


# ---------------------------------------------------------------------------
# Upstream 429 retry layer
# ---------------------------------------------------------------------------

import openai
from llm.openrouter_client import _parse_retry_after_seconds


class _FakeResponse:
    """Mimics the openai SDK's httpx.Response surface for retry-after parsing."""

    def __init__(self, body: dict | None = None, headers: dict | None = None):
        self._body = body or {}
        self.headers = headers or {}
        self.status_code = 429
        self.request = None  # openai SDK reads this when constructing the exception

    def json(self) -> dict:
        return self._body


def _make_429(body: dict | None = None, headers: dict | None = None) -> openai.RateLimitError:
    response = _FakeResponse(body=body, headers=headers)
    return openai.RateLimitError(
        message="rate limited",
        response=response,  # type: ignore[arg-type]
        body=body,
    )


def test_parse_retry_after_from_body_metadata():
    """OpenRouter nests upstream provider's wait time under error.metadata.retry_after_seconds."""
    err = _make_429(body={
        "error": {"metadata": {"retry_after_seconds": 29.0}}
    })
    assert _parse_retry_after_seconds(err, default=5.0) == 29.0


def test_parse_retry_after_from_header_fallback():
    """If body lacks retry_after, fall back to the HTTP Retry-After header."""
    err = _make_429(body={"error": {}}, headers={"Retry-After": "15"})
    assert _parse_retry_after_seconds(err, default=5.0) == 15.0


def test_parse_retry_after_returns_default_when_no_info():
    """If neither body nor headers have a delay, return the default."""
    err = _make_429(body={"error": {}}, headers={})
    assert _parse_retry_after_seconds(err, default=7.0) == 7.0


class _FakeRetryFlakyOpenAI:
    """
    Fake openai client whose `chat.completions.create` raises a 429 N times
    then returns a normal response. Records each call's kwargs for assertions.
    """

    def __init__(self, num_429s: int, success_body: str = "ok"):
        self.num_429s_remaining = num_429s
        self.success_body = success_body
        self.calls: list[dict] = []
        self.chat = self  # so client._client.chat.completions.create works

    @property
    def completions(self):
        return self

    def create(self, **kwargs) -> _FakeChatResponse:
        self.calls.append(kwargs)
        if self.num_429s_remaining > 0:
            self.num_429s_remaining -= 1
            raise _make_429(body={
                "error": {"metadata": {"retry_after_seconds": 0.01}}  # fast for tests
            })
        return _FakeChatResponse(self.success_body)


def test_complete_retries_on_upstream_429_and_succeeds(monkeypatch):
    """complete() retries past two 429s and returns the eventual success."""
    flaky = _FakeRetryFlakyOpenAI(num_429s=2, success_body="hello world")
    client = OpenRouterClient(api_key="dummy", upstream_429_max_attempts=4)
    monkeypatch.setattr(client, "_client", flaky)

    result = client.complete("ping")
    assert result.text == "hello world"
    assert len(flaky.calls) == 3  # 2 failures + 1 success


def test_complete_raises_after_exhausting_retry_attempts(monkeypatch):
    """If 429s persist past max_attempts, the last 429 propagates."""
    persistent_flaky = _FakeRetryFlakyOpenAI(num_429s=10)  # more than max_attempts
    client = OpenRouterClient(api_key="dummy", upstream_429_max_attempts=3)
    monkeypatch.setattr(client, "_client", persistent_flaky)

    with pytest.raises(openai.RateLimitError):
        client.complete("ping")
    assert len(persistent_flaky.calls) == 3  # exactly max_attempts attempts


def test_complete_json_uses_retry_layer_too(monkeypatch):
    """The two-attempt JSON fallback also benefits from the retry layer."""
    flaky = _FakeRetryFlakyOpenAI(num_429s=1, success_body='{"name": "x", "score": 0.5}')
    client = OpenRouterClient(api_key="dummy", upstream_429_max_attempts=3)
    monkeypatch.setattr(client, "_client", flaky)

    result = client.complete_json("prompt", schema=_Sample)
    assert result.name == "x"
    # 1 retry + 1 success = 2 calls (then complete_json's attempt 1 succeeds)
    assert len(flaky.calls) == 2


class _FakeEmptyChoicesResponse:
    """
    OpenRouter free-pool's degenerate 200-OK case: choices=None, no usage.
    Verifies the client doesn't crash with TypeError on `choices[0]`.
    """

    def __init__(self, model: str = "openai/gpt-oss-20b:free"):
        self.choices = None
        self.model = model
        self.usage = None


class _FakeOpenAIReturningNoChoices:
    """Fake openai SDK that returns the degenerate empty-choices response."""

    def __init__(self):
        self.chat = self
        self.completions = self
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeEmptyChoicesResponse()


def test_complete_does_not_crash_when_choices_is_none(monkeypatch):
    """Defensive: a response with choices=None must yield empty text, not TypeError."""
    fake = _FakeOpenAIReturningNoChoices()
    client = OpenRouterClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete("ping")
    assert result.text == ""
    assert result.stop_reason == "no_choices"
    # Token counts default to 0 when usage is absent
    assert result.input_tokens == 0
    assert result.output_tokens == 0


def test_complete_json_handles_empty_choices_via_fallback(monkeypatch):
    """
    The two-attempt JSON fallback should engage when attempt 1 returns
    empty content due to choices=None.
    """
    # Mix: 1st call returns degenerate empty-choices; 2nd call returns valid JSON
    class _MixedFake:
        def __init__(self):
            self.chat = self
            self.completions = self
            self._call_n = 0
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            self._call_n += 1
            if self._call_n == 1:
                return _FakeEmptyChoicesResponse()
            return _FakeChatResponse('{"name": "x", "score": 0.5}')

    fake = _MixedFake()
    client = OpenRouterClient(api_key="dummy")
    monkeypatch.setattr(client, "_client", fake)

    result = client.complete_json("prompt", schema=_Sample)
    assert result.name == "x"
    assert len(fake.calls) == 2  # fallback engaged


def test_complete_logs_429_retry_telemetry(monkeypatch, tmp_path):
    """Each retry should write an openrouter_429_retry event with the delay."""
    flaky = _FakeRetryFlakyOpenAI(num_429s=1, success_body="ok")
    rc = RunContext(name="test", base_dir=tmp_path)
    client = OpenRouterClient(api_key="dummy", run_context=rc, upstream_429_max_attempts=3)
    monkeypatch.setattr(client, "_client", flaky)

    client.complete("ping")

    import json
    events = [json.loads(line) for line in (rc.dir / "events.jsonl").read_text().splitlines()]
    retry_events = [e for e in events if e["event"] == "openrouter_429_retry"]
    assert len(retry_events) == 1
    assert retry_events[0]["attempt"] == 1
    assert retry_events[0]["sleep_seconds"] == 0.01
