#!/usr/bin/env python
"""
Smoke-test the OpenRouter integration.

Modes:
    # 1. Verify key + default model — one tiny 'hello' call
    python scripts/ping_openrouter.py

    # 2. List currently-available free models on OpenRouter
    python scripts/ping_openrouter.py --list-free

    # 3. Verify every per-role configured model is reachable on OpenRouter
    python scripts/ping_openrouter.py --check-roles

    # 4. Ping a specific model
    python scripts/ping_openrouter.py --model deepseek/deepseek-r1:free

Designed to fail loudly with a clear message on any of the common setup
mistakes: missing key, lowercase env var name, dead model ID, exhausted
rate limit, paid model requested without credits.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import requests  # noqa: E402

from config import (  # noqa: E402
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_DEFAULT_MODEL,
    OPENROUTER_MODEL_CHALLENGER,
    OPENROUTER_MODEL_ORGANIZATIONAL,
    OPENROUTER_MODEL_REGULATORY,
    OPENROUTER_MODEL_TECHNICAL,
    OPENROUTER_MODEL_V1_EXTRACTION,
    OPENROUTER_MODEL_V5_CONFIRMATION,
    OPENROUTER_MODEL_V6_REPORT,
)
from llm.openrouter_client import OpenRouterClient  # noqa: E402


ROLE_MODELS: list[tuple[str, str]] = [
    ("default", OPENROUTER_DEFAULT_MODEL),
    ("v1_extraction", OPENROUTER_MODEL_V1_EXTRACTION),
    ("v4_technical", OPENROUTER_MODEL_TECHNICAL),
    ("v4_organizational", OPENROUTER_MODEL_ORGANIZATIONAL),
    ("v4_challenger", OPENROUTER_MODEL_CHALLENGER),
    ("v4_regulatory", OPENROUTER_MODEL_REGULATORY),
    ("v5_confirmation", OPENROUTER_MODEL_V5_CONFIRMATION),
    ("v6_report", OPENROUTER_MODEL_V6_REPORT),
]


def _require_key() -> None:
    if not OPENROUTER_API_KEY:
        print(
            "FAIL: OPENROUTER_API_KEY is not set in the environment.\n"
            "Check your .env: the variable name must be uppercase (OPENROUTER_API_KEY=...), "
            "no spaces around `=`. python-dotenv is case-sensitive.",
            file=sys.stderr,
        )
        sys.exit(2)


def list_free_models() -> None:
    """List all currently-free models on OpenRouter."""
    _require_key()
    print(f"Fetching model catalog from {OPENROUTER_BASE_URL}/models ...")
    r = requests.get(
        f"{OPENROUTER_BASE_URL}/models",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"FAIL: GET /models returned {r.status_code}: {r.text[:300]}",
              file=sys.stderr)
        sys.exit(2)

    data = r.json().get("data", [])
    free = []
    for m in data:
        pricing = m.get("pricing", {}) or {}
        # OpenRouter marks free models with all prices == "0"
        if all(str(pricing.get(k, "0")) == "0" for k in ("prompt", "completion")):
            free.append(m)

    free.sort(key=lambda m: m.get("id", ""))
    print(f"\n{len(free)} free models currently available:\n")
    for m in free:
        ctx = m.get("context_length", "?")
        print(f"  {m['id']:<60}  ctx={ctx}")


def ping_model(model: str) -> bool:
    """Run a tiny 'reply with the word OK' call against `model`. Returns success."""
    _require_key()
    print(f"  → {model:<60} ", end="", flush=True)
    try:
        # 200 tokens, not 20 — reasoning-tuned models (e.g. nemotron-*-reasoning)
        # burn most of their budget on internal `reasoning` tokens before
        # emitting visible content. 20 leaves nothing for the answer; 200 does.
        client = OpenRouterClient(model=model, max_tokens=200)
        result = client.complete(
            "Reply with exactly the two-letter word: OK",
            temperature=0.0,
        )
        text = result.text.strip()
        ok = "OK" in text.upper()
        marker = "PASS" if ok else "WARN"
        print(f"[{marker}]  echoed_model={result.model}  reply={text[:40]!r}")
        return ok
    except Exception as e:
        print(f"[FAIL]  {type(e).__name__}: {e}")
        return False


def check_roles() -> int:
    print("\nChecking each per-role configured model:\n")
    failed = 0
    seen: set[str] = set()
    for role, model in ROLE_MODELS:
        if model in seen:
            print(f"  → {model:<60}  [SKIP — already checked]")
            continue
        seen.add(model)
        if not ping_model(model):
            failed += 1
    print(
        f"\n{len(seen) - failed}/{len(seen)} reachable. "
        f"{failed} failed."
    )
    return failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-free", action="store_true",
                        help="List currently-free OpenRouter models and exit.")
    parser.add_argument("--check-roles", action="store_true",
                        help="Ping every per-role configured model.")
    parser.add_argument("--model", type=str, default=None,
                        help="Ping a specific model ID.")
    args = parser.parse_args()

    if args.list_free:
        list_free_models()
        return 0

    if args.check_roles:
        return 1 if check_roles() > 0 else 0

    target = args.model or OPENROUTER_DEFAULT_MODEL
    print(f"Pinging OpenRouter ({OPENROUTER_BASE_URL}) with model: {target}\n")
    return 0 if ping_model(target) else 1


if __name__ == "__main__":
    sys.exit(main())
