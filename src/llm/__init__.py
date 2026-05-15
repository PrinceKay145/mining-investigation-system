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

from config import (
    LLM_PROVIDER,
    OPENROUTER_MODEL_V1_EXTRACTION,
    OPENROUTER_MODEL_V5_CONFIRMATION,
    OPENROUTER_MODEL_V6_REPORT,
)
from llm.client import AnthropicClient, CompletionResult
from llm.logging import RunContext
from llm.openai_client import OpenAIClient
from llm.openrouter_client import OpenRouterClient

__all__ = [
    "LLMClient",
    "AnthropicClient",
    "OpenAIClient",
    "OpenRouterClient",
    "CompletionResult",
    "RunContext",
    "make_llm_client",
    "make_role_client",
]

# Roles → OpenRouter env var. Only consulted when LLM_PROVIDER=openrouter;
# other providers don't differentiate by role (single model per account).
_ROLE_TO_OPENROUTER_MODEL = {
    "v1_extraction": OPENROUTER_MODEL_V1_EXTRACTION,
    "v5_confirmation": OPENROUTER_MODEL_V5_CONFIRMATION,
    "v6_report": OPENROUTER_MODEL_V6_REPORT,
}

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
    if p == "openrouter":
        return OpenRouterClient(model=model, run_context=run_context)
    raise ValueError(
        f"Unknown LLM_PROVIDER: '{p}'. "
        f"Expected 'anthropic', 'openai', or 'openrouter'."
    )


def make_role_client(
    role: str,
    *,
    run_context: RunContext | None = None,
) -> LLMClient:
    """
    Build a client for a single-client subsystem role (v1 mode-2 extraction,
    v5 confirmation, v6 report) with role-specific model selection.

    - `LLM_PROVIDER == "openrouter"`: returns an `OpenRouterClient` with the
      role's model pulled from `OPENROUTER_MODEL_V{1,5,6}_*` env vars. See
      note.md "LLM provisioning" for why each role gets its own model.
    - Any other provider: falls through to `make_llm_client(run_context=...)`.
      Anthropic/OpenAI accounts run a single model; no per-role differentiation.

    For v4's four agents, use `build_v4_agent_clients()` from `v4_agents`
    — they're handled separately because v4 has a fixed 4-agent topology.

    Args:
        role: One of `"v1_extraction"`, `"v5_confirmation"`, `"v6_report"`.
        run_context: Optional RunContext for per-call telemetry.

    Raises:
        ValueError: if `role` is not a known role string.
    """
    if LLM_PROVIDER == "openrouter":
        if role not in _ROLE_TO_OPENROUTER_MODEL:
            raise ValueError(
                f"Unknown role: {role!r}. "
                f"Expected one of {sorted(_ROLE_TO_OPENROUTER_MODEL.keys())}."
            )
        return OpenRouterClient(
            model=_ROLE_TO_OPENROUTER_MODEL[role],
            run_context=run_context,
        )
    return make_llm_client(run_context=run_context)
