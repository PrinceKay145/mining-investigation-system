"""
AnthropicClient — thin wrapper around the anthropic SDK.

Responsibilities:
  - Read API key + model from env (via config.py) with constructor overrides
  - Single `complete()` method returning a typed CompletionResult
  - Optional structured output via `complete_json(schema)` — uses the schema's
    JSON schema to constrain the model and parses the response into the
    Pydantic model
  - Records each call as a `llm_call` event on the RunContext logger:
    model, input_tokens, output_tokens, latency_ms, prompt_preview,
    response_preview

Why a wrapper:
  - One canonical place for retry policy, telemetry, and JSON-mode parsing
  - Tests can mock the client surface without touching the anthropic SDK
  - v4 agents and v5/v6 callers all share the same call path

The wrapper deliberately does not try to abstract anthropic-specific options
beyond the common cases. For exotic features (vision, tools), call
`self._client.messages.create(...)` directly via `client.raw`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from config import ANTHROPIC_API_KEY, DEFAULT_LLM_MODEL
from llm.logging import RunContext


T = TypeVar("T", bound=BaseModel)


@dataclass
class CompletionResult:
    """Outcome of one model call."""
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    stop_reason: str | None


class AnthropicClient:
    """
    Convenience wrapper around `anthropic.Anthropic`.

    Args:
        api_key: Override env-loaded ANTHROPIC_API_KEY.
        model: Override env-loaded LLM_MODEL (default claude-opus-4-7).
        max_tokens: Default for `complete()` if not overridden per-call.
        max_retries: Forwarded to the anthropic SDK (handles 429/5xx).
        run_context: Optional RunContext for telemetry. If None, calls are
                     not logged structurally — useful for ad-hoc REPL use.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        max_retries: int = 2,
        run_context: RunContext | None = None,
    ):
        key = api_key or ANTHROPIC_API_KEY
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to .env (see .env.example) "
                "or pass api_key= explicitly."
            )
        self._client = anthropic.Anthropic(api_key=key, max_retries=max_retries)
        self.model: str = model or DEFAULT_LLM_MODEL
        self.max_tokens: int = max_tokens
        self.run: RunContext | None = run_context

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def raw(self) -> anthropic.Anthropic:
        """Escape hatch to the underlying anthropic client for advanced features."""
        return self._client

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 1.0,
    ) -> CompletionResult:
        """Send a single user message; return the model's text response."""
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        start = time.monotonic()
        response = self._client.messages.create(**kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)

        text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )

        result = CompletionResult(
            text=text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=latency_ms,
            stop_reason=response.stop_reason,
        )

        if self.run is not None:
            self.run.event(
                "llm_call",
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
                stop_reason=result.stop_reason,
                prompt_preview=_preview(prompt),
                response_preview=_preview(result.text),
            )

        return result

    def complete_json(
        self,
        prompt: str,
        schema: type[T],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> T:
        """
        Send a prompt; parse the response as JSON conforming to `schema`.

        We append a system instruction asking the model to return only valid
        JSON matching the schema. The response is parsed into the Pydantic
        model. Raises `ValidationError` if the model produced malformed JSON
        or fields don't match.

        Lower temperature (0.0) is the default here — JSON outputs benefit
        from determinism more than free-text completions do.
        """
        json_instruction = (
            f"You must respond with a single JSON object that conforms to "
            f"this schema:\n\n{json.dumps(schema.model_json_schema(), indent=2)}\n\n"
            f"Return only the JSON object — no prose, no code fences, no commentary."
        )
        full_system = (
            f"{system}\n\n{json_instruction}" if system else json_instruction
        )
        result = self.complete(
            prompt=prompt,
            system=full_system,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        text = result.text.strip()
        # Strip ```json fences if the model included them despite instructions
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text[: -3]
            text = text.strip()

        try:
            return schema.model_validate_json(text)
        except ValidationError as e:
            raise ValueError(
                f"Model response did not conform to {schema.__name__}.\n"
                f"--- Raw response ---\n{text}\n--- End response ---\n"
                f"Validation error: {e}"
            ) from e


def _preview(s: str, n: int = 200) -> str:
    """Truncate long strings for the events log; full text lives in artifacts."""
    s = s.strip()
    return s if len(s) <= n else s[:n - 3] + "..."
