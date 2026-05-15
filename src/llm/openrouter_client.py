"""
OpenRouterClient — talks to OpenRouter's OpenAI-compatible endpoint at
https://openrouter.ai/api/v1. Same surface as AnthropicClient / OpenAIClient
(`complete`, `complete_json`); v4 orchestrator can use any of them.

Adds one capability over OpenAIClient: a retry-with-stricter-prompt fallback
in `complete_json`. Some free reasoning models on OpenRouter (notably
DeepSeek R1) intermittently return empty content or non-JSON text under
`response_format={"type": "json_object"}`. The fallback drops response_format
and inlines the schema + an explicit "JSON only, first character must be `{`"
instruction into the user message.

Typical use: one instance per v4 agent, each with its own model. See
config.OPENROUTER_MODEL_* env vars for per-role defaults.
"""

from __future__ import annotations

import json
import time
from typing import Any, TypeVar

import openai
from pydantic import BaseModel, ValidationError

from config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_DEFAULT_MODEL,
    OPENROUTER_HTTP_REFERER,
    OPENROUTER_X_TITLE,
)
from llm.client import CompletionResult
from llm.logging import RunContext


T = TypeVar("T", bound=BaseModel)


class OpenRouterClient:
    """OpenRouter wrapper with the AnthropicClient / OpenAIClient interface."""

    # Default retry policy for upstream 429s. The OpenAI SDK's built-in
    # retries cap their backoff around 8–10s, but OpenRouter's free-pool
    # providers (notably Venice) return retry-after windows of ~30s. These
    # constants drive our outer retry loop; constructor kwargs override.
    _DEFAULT_429_MAX_ATTEMPTS = 4   # initial call + 3 retries
    _DEFAULT_429_FALLBACK_DELAY = 5.0   # used only if retry_after_seconds missing
    _DEFAULT_429_MAX_DELAY = 60.0       # cap, even if upstream says wait longer

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        max_retries: int = 5,
        run_context: RunContext | None = None,
        upstream_429_max_attempts: int | None = None,
        upstream_429_max_delay: float | None = None,
    ):
        key = api_key or OPENROUTER_API_KEY
        if not key:
            raise RuntimeError(
                "OPENROUTER_API_KEY not set. Add it to .env (see .env.example) "
                "or pass api_key= explicitly."
            )

        # OpenRouter attribution headers — picked up from env if set.
        default_headers: dict[str, str] = {}
        if OPENROUTER_HTTP_REFERER:
            default_headers["HTTP-Referer"] = OPENROUTER_HTTP_REFERER
        if OPENROUTER_X_TITLE:
            default_headers["X-Title"] = OPENROUTER_X_TITLE

        self._client = openai.OpenAI(
            api_key=key,
            base_url=OPENROUTER_BASE_URL,
            max_retries=max_retries,
            default_headers=default_headers or None,
        )
        self.model: str = model or OPENROUTER_DEFAULT_MODEL
        self.max_tokens: int = max_tokens
        self.run: RunContext | None = run_context
        self.upstream_429_max_attempts: int = (
            upstream_429_max_attempts if upstream_429_max_attempts is not None
            else self._DEFAULT_429_MAX_ATTEMPTS
        )
        self.upstream_429_max_delay: float = (
            upstream_429_max_delay if upstream_429_max_delay is not None
            else self._DEFAULT_429_MAX_DELAY
        )

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

        start = time.monotonic()
        response = self._call_with_retry(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        text, finish_reason = _extract_text_and_finish_reason(response)

        result = CompletionResult(
            text=text,
            model=response.model,
            input_tokens=_safe_usage(response, "prompt_tokens"),
            output_tokens=_safe_usage(response, "completion_tokens"),
            latency_ms=latency_ms,
            stop_reason=finish_reason,
        )

        if self.run is not None:
            self.run.event(
                "llm_call",
                provider="openrouter",
                model=result.model,
                requested_model=self.model,
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

        Two attempts, in order:
          1. response_format={"type": "json_object"} with schema in system prompt.
          2. No response_format; schema and strict "JSON only" rule inlined into
             the user message. This rescues empty-content / leaked-reasoning
             responses from models like DeepSeek R1.

        Raises ValueError if both attempts fail to produce schema-valid JSON.
        """
        schema_json = json.dumps(schema.model_json_schema(), indent=2)

        # ----- Attempt 1: native response_format -----
        a1_system = _build_json_system(system, schema_json)
        a1_text, a1_meta = self._chat(
            messages=[
                {"role": "system", "content": a1_system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        parsed = _try_parse(a1_text, schema)

        # ----- Attempt 2: prompt-only enforcement -----
        used_fallback = False
        a2_meta: dict[str, Any] | None = None
        if parsed is None:
            used_fallback = True
            a2_user = (
                f"{prompt}\n\n"
                f"---\n"
                f"Respond with a single JSON object matching this exact schema:\n"
                f"{schema_json}\n\n"
                f"Output ONLY the JSON object. No reasoning, no prose, no "
                f"markdown fences. The first character of your response MUST "
                f"be `{{` and the last character MUST be `}}`."
            )
            a2_system = system or (
                "You are a precise JSON-emitting assistant. You respond with "
                "exactly one JSON object and nothing else."
            )
            a2_text, a2_meta = self._chat(
                messages=[
                    {"role": "system", "content": a2_system},
                    {"role": "user", "content": a2_user},
                ],
                max_tokens=max_tokens or self.max_tokens,
                temperature=temperature,
                response_format=None,
            )
            parsed = _try_parse(a2_text, schema)
        else:
            a2_text = ""

        # ----- Telemetry -----
        if self.run is not None:
            final_meta = a2_meta if used_fallback else a1_meta
            self.run.event(
                "llm_call",
                provider="openrouter",
                model=final_meta["model"],
                requested_model=self.model,
                input_tokens=final_meta["input_tokens"],
                output_tokens=final_meta["output_tokens"],
                latency_ms=final_meta["latency_ms"],
                stop_reason=final_meta["finish_reason"],
                response_format="prompt-only" if used_fallback else "json_object",
                used_fallback=used_fallback,
                prompt_preview=_preview(prompt),
                response_preview=_preview(a2_text if used_fallback else a1_text),
            )

        if parsed is None:
            raise ValueError(
                f"OpenRouter model '{self.model}' did not produce JSON matching "
                f"{schema.__name__} after 2 attempts.\n"
                f"--- Attempt 1 (response_format=json_object) ---\n{a1_text}\n"
                f"--- Attempt 2 (prompt-only) ---\n{a2_text}\n"
                f"--- End ---"
            )
        return parsed

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _call_with_retry(self, **kwargs: Any) -> Any:
        """
        Call `chat.completions.create` with retry on upstream 429s.

        Why this is a separate layer on top of the OpenAI SDK's built-in
        retries: OpenRouter's free-pool providers (notably Venice) respond
        with a 429 whose body has `error.metadata.retry_after_seconds ≈ 30`,
        which exceeds the SDK's default backoff window (~8–10s total). The
        SDK exhausts its retries before the upstream cools down; we wrap
        with an explicit longer-wait retry that honors the upstream-provided
        delay.

        On 429: parse `retry_after_seconds` from the error body (falling
        back to `Retry-After` header, then to `_DEFAULT_429_FALLBACK_DELAY`),
        clamp to `upstream_429_max_delay`, sleep, retry. Up to
        `upstream_429_max_attempts` total attempts.

        Other openai exception types propagate without retry.
        """
        last_exc: openai.RateLimitError | None = None
        for attempt in range(self.upstream_429_max_attempts):
            try:
                return self._client.chat.completions.create(**kwargs)
            except openai.RateLimitError as e:
                last_exc = e
                if attempt == self.upstream_429_max_attempts - 1:
                    break
                delay = min(
                    _parse_retry_after_seconds(e, default=self._DEFAULT_429_FALLBACK_DELAY),
                    self.upstream_429_max_delay,
                )
                if self.run is not None:
                    self.run.event(
                        "openrouter_429_retry",
                        requested_model=kwargs.get("model"),
                        attempt=attempt + 1,
                        max_attempts=self.upstream_429_max_attempts,
                        sleep_seconds=delay,
                        error_excerpt=str(e)[:200],
                    )
                time.sleep(delay)
        # All attempts exhausted — re-raise the last 429
        assert last_exc is not None  # for type checker
        raise last_exc

    def _chat(
        self,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        response_format: dict | None,
    ) -> tuple[str, dict[str, Any]]:
        """Single chat.completions.create call. Returns (text, metadata)."""
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        start = time.monotonic()
        response = self._call_with_retry(**kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)

        text, finish_reason = _extract_text_and_finish_reason(response)
        meta = {
            "model": response.model,
            "input_tokens": _safe_usage(response, "prompt_tokens"),
            "output_tokens": _safe_usage(response, "completion_tokens"),
            "latency_ms": latency_ms,
            "finish_reason": finish_reason,
        }
        return text.strip(), meta


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _build_json_system(user_system: str | None, schema_json: str) -> str:
    instruction = (
        f"You must respond with a single JSON object that conforms to this "
        f"schema:\n\n{schema_json}\n\n"
        f"Return only the JSON object — no prose, no markdown fences."
    )
    return f"{user_system}\n\n{instruction}" if user_system else instruction


def _try_parse(text: str, schema: type[T]) -> T | None:
    """Attempt to parse `text` as JSON matching `schema`. Returns None on failure."""
    if not text:
        return None
    # Strip ```json fences if a model added them despite instructions.
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return schema.model_validate_json(text)
    except (ValidationError, json.JSONDecodeError, ValueError):
        return None


def _preview(s: str, n: int = 200) -> str:
    """Truncate long strings for the events log."""
    s = s.strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _extract_text_and_finish_reason(response: Any) -> tuple[str, str]:
    """
    Pull `text` and `finish_reason` from a ChatCompletion response, defending
    against degenerate cases where the OpenAI SDK hands us a `choices=None`
    or empty `choices` list.

    Why this is necessary: a small fraction of OpenRouter free-pool responses
    come back as 200-OK with `choices=None` — typically an upstream provider
    returning an error payload that the OpenRouter gateway accepts as
    "successful" but doesn't backfill `choices` for. Without this guard,
    `response.choices[0]` raises TypeError mid-loop, which historically
    crashed long v5 confirmation runs (~50+ pair-check calls in flight).

    The empty-text path is *not* an exception case for `complete_json` — its
    two-attempt fallback already handles empty `content`; this function just
    ensures the empty case lands there instead of throwing.

    Returns (text, finish_reason). On the degenerate empty-choices path,
    returns ("", "no_choices") so the caller can log the failure mode without
    confusing it with a normal `stop`.
    """
    choices = getattr(response, "choices", None) or []
    if not choices:
        return "", "no_choices"
    choice = choices[0]
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None) if message is not None else None
    finish_reason = getattr(choice, "finish_reason", None) or "unknown"
    return (content or ""), finish_reason


def _safe_usage(response: Any, field: str) -> int:
    """Read a token count off `response.usage.<field>`, returning 0 if absent."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0
    return int(getattr(usage, field, 0) or 0)


def _parse_retry_after_seconds(exc: openai.RateLimitError, default: float) -> float:
    """
    Extract a retry-after delay from a 429 response.

    Looks in order:
      1. `error.metadata.retry_after_seconds` in the JSON body — this is
         where OpenRouter nests the upstream provider's instruction (e.g.
         Venice returns ~29 seconds here).
      2. `Retry-After` HTTP header (RFC 7231 fallback).
      3. The provided `default`.

    Any parsing failure silently falls through to the next source.
    """
    # Source 1: parsed body
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        try:
            metadata = body.get("error", {}).get("metadata", {})
            retry = metadata.get("retry_after_seconds")
            if retry is not None:
                return float(retry)
        except (AttributeError, TypeError, ValueError):
            pass
    # Source 2: raw response (if openai SDK gave us one)
    response = getattr(exc, "response", None)
    if response is not None:
        # 2a: response.json()
        try:
            data = response.json()
            retry = data.get("error", {}).get("metadata", {}).get("retry_after_seconds")
            if retry is not None:
                return float(retry)
        except (AttributeError, ValueError, KeyError, TypeError):
            pass
        # 2b: Retry-After header
        try:
            headers = response.headers
            h = headers.get("Retry-After") or headers.get("retry-after")
            if h:
                return float(h)
        except (AttributeError, TypeError, ValueError):
            pass
    return default
