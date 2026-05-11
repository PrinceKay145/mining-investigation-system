"""
OpenAIClient — wrapper around the openai SDK mirroring AnthropicClient's interface.

Same shape as `llm.client.AnthropicClient`: `complete()` returns a
`CompletionResult`, `complete_json(schema=...)` returns a parsed Pydantic
instance. The v4 orchestrator treats both clients identically — pass either
to `run_v4(..., client=...)`.

Differences from the Anthropic client (transparent to callers):
  - OpenAI puts the system message in the `messages` array (role="system")
    rather than as a top-level `system` parameter
  - JSON-mode uses `response_format={"type": "json_object"}` — a hard
    constraint enforced by the API, more reliable than Anthropic's
    prompt-instruction approach
  - Token field names: `prompt_tokens` / `completion_tokens` instead of
    `input_tokens` / `output_tokens`
"""

from __future__ import annotations

import json
import time
from typing import TypeVar

import openai
from pydantic import BaseModel, ValidationError

from config import DEFAULT_OPENAI_MODEL, OPENAI_API_KEY
from llm.client import CompletionResult
from llm.logging import RunContext


T = TypeVar("T", bound=BaseModel)


class OpenAIClient:
    """OpenAI Chat Completions wrapper with the AnthropicClient interface."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        max_retries: int = 2,
        run_context: RunContext | None = None,
    ):
        key = api_key or OPENAI_API_KEY
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Add it to .env (see .env.example) "
                "or pass api_key= explicitly."
            )
        self._client = openai.OpenAI(api_key=key, max_retries=max_retries)
        self.model: str = model or DEFAULT_OPENAI_MODEL
        self.max_tokens: int = max_tokens
        self.run: RunContext | None = run_context

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def raw(self) -> openai.OpenAI:
        """Escape hatch to the underlying openai client for advanced features."""
        return self._client

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 1.0,
    ) -> CompletionResult:
        """Send a single user message; return the model's text response."""
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature,
        }

        start = time.monotonic()
        response = self._client.chat.completions.create(**kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        text = choice.message.content or ""

        result = CompletionResult(
            text=text,
            model=response.model,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            latency_ms=latency_ms,
            stop_reason=choice.finish_reason,
        )

        if self.run is not None:
            self.run.event(
                "llm_call",
                provider="openai",
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

        Uses OpenAI's native JSON mode (`response_format={"type": "json_object"}`)
        for hard-constrained output. The system message is augmented with the
        target schema so the model knows the field structure.
        """
        json_instruction = (
            f"You must respond with a single JSON object that conforms to "
            f"this schema:\n\n{json.dumps(schema.model_json_schema(), indent=2)}\n\n"
            f"Return only the JSON object — no prose, no markdown fences."
        )
        full_system = (
            f"{system}\n\n{json_instruction}" if system else json_instruction
        )

        messages: list[dict] = [
            {"role": "system", "content": full_system},
            {"role": "user", "content": prompt},
        ]

        start = time.monotonic()
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        text = (choice.message.content or "").strip()

        if self.run is not None:
            self.run.event(
                "llm_call",
                provider="openai",
                model=response.model,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                latency_ms=latency_ms,
                stop_reason=choice.finish_reason,
                response_format="json_object",
                prompt_preview=_preview(prompt),
                response_preview=_preview(text),
            )

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
    return s if len(s) <= n else s[: n - 3] + "..."
