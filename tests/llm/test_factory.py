"""Tests for `make_llm_client` — the provider-agnostic factory."""

import pytest

from llm import AnthropicClient, LLMClient, OpenAIClient, make_llm_client


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


def test_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        make_llm_client(provider="grok")


def test_factory_forwards_model_override(monkeypatch):
    monkeypatch.setattr("llm.openai_client.OPENAI_API_KEY", "dummy")
    client = make_llm_client(provider="openai", model="gpt-4o-mini")
    assert client.model == "gpt-4o-mini"


def test_both_clients_satisfy_protocol(monkeypatch):
    monkeypatch.setattr("llm.client.ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setattr("llm.openai_client.OPENAI_API_KEY", "dummy")
    a = AnthropicClient()
    o = OpenAIClient()
    # Both should pass an isinstance check against the runtime-checkable Protocol
    assert isinstance(a, LLMClient)
    assert isinstance(o, LLMClient)
