"""Tests for `make_llm_client` — the provider-agnostic factory."""

import pytest

from llm import (
    AnthropicClient,
    LLMClient,
    OpenAIClient,
    OpenRouterClient,
    make_llm_client,
    make_role_client,
)


def test_factory_returns_anthropic_by_default(monkeypatch):
    monkeypatch.setattr("llm.LLM_PROVIDER", "anthropic")
    monkeypatch.setattr("llm.client.ANTHROPIC_API_KEY", "dummy")
    client = make_llm_client()
    assert isinstance(client, AnthropicClient)


def test_factory_returns_openai_when_provider_is_openai(monkeypatch):
    monkeypatch.setattr("llm.LLM_PROVIDER", "openai")
    monkeypatch.setattr("llm.openai_client.OPENAI_API_KEY", "dummy")
    client = make_llm_client()
    assert isinstance(client, OpenAIClient)


def test_factory_provider_argument_overrides_env(monkeypatch):
    monkeypatch.setattr("llm.LLM_PROVIDER", "anthropic")
    monkeypatch.setattr("llm.openai_client.OPENAI_API_KEY", "dummy")
    client = make_llm_client(provider="openai")
    assert isinstance(client, OpenAIClient)


def test_factory_provider_argument_is_case_insensitive(monkeypatch):
    monkeypatch.setattr("llm.openai_client.OPENAI_API_KEY", "dummy")
    client = make_llm_client(provider="OpenAI")
    assert isinstance(client, OpenAIClient)


def test_factory_returns_openrouter_when_provider_is_openrouter(monkeypatch):
    monkeypatch.setattr("llm.LLM_PROVIDER", "openrouter")
    monkeypatch.setattr("llm.openrouter_client.OPENROUTER_API_KEY", "dummy")
    client = make_llm_client()
    assert isinstance(client, OpenRouterClient)


def test_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        make_llm_client(provider="grok")


def test_factory_forwards_model_override(monkeypatch):
    monkeypatch.setattr("llm.openai_client.OPENAI_API_KEY", "dummy")
    client = make_llm_client(provider="openai", model="gpt-4o-mini")
    assert client.model == "gpt-4o-mini"


def test_all_clients_satisfy_protocol(monkeypatch):
    monkeypatch.setattr("llm.client.ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setattr("llm.openai_client.OPENAI_API_KEY", "dummy")
    monkeypatch.setattr("llm.openrouter_client.OPENROUTER_API_KEY", "dummy")
    a = AnthropicClient()
    o = OpenAIClient()
    r = OpenRouterClient()
    # All three should pass an isinstance check against the runtime-checkable Protocol
    assert isinstance(a, LLMClient)
    assert isinstance(o, LLMClient)
    assert isinstance(r, LLMClient)


# ---------------------------------------------------------------------------
# make_role_client
# ---------------------------------------------------------------------------

def test_make_role_client_returns_openrouter_with_role_model(monkeypatch):
    """Under openrouter, each role gets its dedicated OPENROUTER_MODEL_* model."""
    monkeypatch.setattr("llm.LLM_PROVIDER", "openrouter")
    monkeypatch.setattr("llm.openrouter_client.OPENROUTER_API_KEY", "dummy")
    monkeypatch.setattr("llm._ROLE_TO_OPENROUTER_MODEL", {
        "v1_extraction": "model-v1",
        "v5_confirmation": "model-v5",
        "v6_report": "model-v6",
    })

    assert make_role_client("v1_extraction").model == "model-v1"
    assert make_role_client("v5_confirmation").model == "model-v5"
    assert make_role_client("v6_report").model == "model-v6"


def test_make_role_client_falls_through_for_non_openrouter_providers(monkeypatch):
    """Anthropic/OpenAI accounts run a single model — role distinction is a no-op."""
    monkeypatch.setattr("llm.LLM_PROVIDER", "anthropic")
    monkeypatch.setattr("llm.client.ANTHROPIC_API_KEY", "dummy")
    client = make_role_client("v5_confirmation")
    assert isinstance(client, AnthropicClient)


def test_make_role_client_rejects_unknown_role(monkeypatch):
    monkeypatch.setattr("llm.LLM_PROVIDER", "openrouter")
    monkeypatch.setattr("llm.openrouter_client.OPENROUTER_API_KEY", "dummy")
    with pytest.raises(ValueError, match="Unknown role"):
        make_role_client("v99_imaginary")
