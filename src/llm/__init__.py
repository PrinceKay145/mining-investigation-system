"""
LLM scaffolding — provider-agnostic interface, anthropic + openai backends, run-scoped logging.

Public surface:
  - `LLMClient` — Protocol that both AnthropicClient and OpenAIClient satisfy.
                  The v4 orchestrator's `client` parameter takes any LLMClient.
  - `AnthropicClient`, `OpenAIClient` — concrete implementations.
  - `make_llm_client(...)` — factory that picks the right backend based on
                             the `LLM_PROVIDER` env var (defaults to "anthropic").
  - `CompletionResult` — shared return type for `complete()`.
  - `RunContext` — per-run telemetry holder (artifact dir, JSONL events).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable, TypeVar

from pydantic import BaseModel

from config import LLM_PROVIDER
from llm.client import AnthropicClient, CompletionResult
from llm.logging import RunContext
from llm.openai_client import OpenAIClient

__all__ = [
    "LLMClient",
    "AnthropicClient",
    "OpenAIClient",
    "CompletionResult",
    "RunContext",
    "make_llm_client",
]

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMClient(Protocol):
    """
    Protocol both AnthropicClient and OpenAIClient satisfy.

    Any object exposing these two methods (with this shape) is a valid LLM
    client for the v4 orchestrator. Used as the type hint there so the
    orchestrator doesn't import either concrete class.
    """

    model: str

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 1.0,
    ) -> CompletionResult:
        ...

    def complete_json(
        self,
        prompt: str,
        schema: type[T],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> T:
        ...


def make_llm_client(
    *,
    provider: str | None = None,
    model: str | None = None,
    run_context: RunContext | None = None,
) -> LLMClient:
    """
    Construct the LLM client for the active provider.

    Args:
        provider: Override `LLM_PROVIDER` env var. One of "anthropic" or "openai".
        model: Override the provider-specific default model.
        run_context: Optional RunContext for telemetry. Forwarded to the client.

    Returns:
        An `AnthropicClient` or `OpenAIClient` (both satisfy the `LLMClient`
        Protocol).

    Raises:
        ValueError: if `provider` is unrecognized.
        RuntimeError: if the chosen provider's API key is not set.
    """
    p = (provider or LLM_PROVIDER).lower()
    if p == "anthropic":
        return AnthropicClient(model=model, run_context=run_context)
    if p == "openai":
        return OpenAIClient(model=model, run_context=run_context)
    raise ValueError(
        f"Unknown LLM_PROVIDER: '{p}'. Expected 'anthropic' or 'openai'."
    )
