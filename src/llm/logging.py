"""
RunContext — per-pipeline-run state: run_id, output directory, structured logger.

Every pipeline invocation creates a `RunContext`, which:
  - Generates a timestamp-based run_id
  - Mkdirs `runs/<run_id>/` for artifacts (or under a custom base_dir for tests)
  - Writes structured events to `events.jsonl` (one event per line)
  - Mirrors human-readable lines to stdout via stdlib logging
  - Provides `save_artifact(name, data)` for stage-by-stage I/O dumps

Design notes:
  - JSON logging is deliberately stdlib-only — no structlog dependency.
  - events.jsonl is append-only. Each event is a JSON object with at minimum:
      timestamp, event, run_id, plus any kwargs the caller passed.
  - save_artifact handles dicts/lists, Pydantic models (via model_dump), and
    plain strings.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from config import DEFAULT_LOG_LEVEL, RUNS_DIR


class RunContext:
    """Per-run state holder. Create once at the top of a pipeline invocation."""

    def __init__(
        self,
        name: str = "run",
        base_dir: Path | None = None,
        log_level: str | None = None,
    ):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.run_id: str = f"{name}_{ts}"
        self.dir: Path = (base_dir or RUNS_DIR) / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)

        self._events_path: Path = self.dir / "events.jsonl"
        self._logger: logging.Logger = self._build_logger(log_level or DEFAULT_LOG_LEVEL)

    # -- public API ---------------------------------------------------------

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    def event(self, event: str, **kwargs: Any) -> None:
        """Append a structured event to events.jsonl and log it to stdout."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "run_id": self.run_id,
            "event": event,
            **kwargs,
        }
        with open(self._events_path, "a") as f:
            f.write(json.dumps(record, default=_json_default) + "\n")
        self._logger.info("%s %s", event, _short_kwargs(kwargs))

    def save_artifact(self, name: str, data: Any) -> Path:
        """
        Write `data` to `runs/<run_id>/<name>.json`.

        Handles dicts/lists/primitives, Pydantic models, and plain strings.
        Returns the path written.
        """
        out = self.dir / f"{name}.json"
        if isinstance(data, str):
            out = self.dir / f"{name}.txt"
            out.write_text(data)
            return out

        if isinstance(data, BaseModel):
            payload = data.model_dump(mode="json")
        elif isinstance(data, list) and data and isinstance(data[0], BaseModel):
            payload = [item.model_dump(mode="json") for item in data]
        else:
            payload = data

        with open(out, "w") as f:
            json.dump(payload, f, indent=2, default=_json_default, ensure_ascii=False)
        return out

    # -- internals ----------------------------------------------------------

    def _build_logger(self, level: str) -> logging.Logger:
        logger = logging.getLogger(f"runctx.{self.run_id}")
        logger.setLevel(level)
        # Avoid double-logging if root logger has handlers configured by the caller
        logger.propagate = False
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "[%(asctime)s] %(levelname)-7s  %(message)s",
                datefmt="%H:%M:%S",
            ))
            logger.addHandler(handler)
        return logger


# ---------------------------------------------------------------------------
# JSON serialization helpers
# ---------------------------------------------------------------------------

def _json_default(obj: Any) -> Any:
    """Fallback serializer for non-JSON-native types in events.jsonl."""
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Not JSON-serializable: {type(obj).__name__}")


def _short_kwargs(kwargs: dict[str, Any]) -> str:
    """One-line summary of event kwargs for stdout — full data is in events.jsonl."""
    parts = []
    for k, v in kwargs.items():
        if isinstance(v, (str, int, float, bool)):
            s = str(v)
            if len(s) > 60:
                s = s[:57] + "..."
            parts.append(f"{k}={s}")
        elif isinstance(v, (list, dict, set)):
            parts.append(f"{k}=<{type(v).__name__} len={len(v)}>")
        else:
            parts.append(f"{k}=<{type(v).__name__}>")
    return " ".join(parts)
