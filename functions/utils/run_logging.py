"""
Lightweight run-scoped logging helpers for token usage and runtime.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_token_entries: List[Dict[str, Any]] = []


def reset_token_log() -> None:
    """Clear token log for a new run."""
    _token_entries.clear()


def log_token_usage(
    usage: str,
    input_tokens: int | None,
    output_tokens: int | None,
    runtime_seconds: float | None,
) -> None:
    entry = {
        "usage": usage,
        "input_token": input_tokens if input_tokens is not None else 0,
        "output_token": output_tokens if output_tokens is not None else 0,
        "runtime": round(runtime_seconds or 0.0, 4),
    }
    _token_entries.append(entry)


def extract_token_counts(response: Any) -> tuple[int | None, int | None]:
    """
    Attempt to extract input/output token counts from a Gemini response object.
    Works with dict-like or attribute-style metadata payloads.
    """
    usage_meta = getattr(response, "usage_metadata", None)
    if usage_meta is None and isinstance(response, dict):
        usage_meta = response.get("usage_metadata")
    if usage_meta is None:
        return None, None

    input_tokens = _get_value(
        usage_meta,
        ["input_tokens", "prompt_token_count", "prompt_tokens"],
    )
    output_tokens = _get_value(
        usage_meta,
        ["output_tokens", "candidates_token_count", "completion_token_count"],
    )
    return input_tokens, output_tokens


def write_run_log(
    *,
    path: str,
    run_id: str,
    status: str,
    runtime_seconds: float,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    entry = {
        "run_id": run_id,
        "status": status,
        "timestamp": int(time.time()),
        "runtime": round(runtime_seconds, 4),
        "entries": list(_token_entries),
        "metadata": metadata or {},
    }

    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if log_path.exists():
        try:
            current = json.loads(log_path.read_text())
            if isinstance(current, list):
                current.append(entry)
            else:
                current = [current, entry]
        except json.JSONDecodeError:
            current = [entry]
    else:
        current = [entry]

    if len(current) > 100:
        current = current[-100:]

    log_path.write_text(json.dumps(current, indent=2, ensure_ascii=False))


def _get_value(usage_meta: Any, possible_keys: list[str]) -> int | None:
    for key in possible_keys:
        if isinstance(usage_meta, dict) and key in usage_meta:
            return usage_meta[key]
        if hasattr(usage_meta, key):
            return getattr(usage_meta, key)
    return None
