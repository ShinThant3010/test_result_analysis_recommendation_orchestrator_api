"""
Run-scoped logging helpers for token usage and runtime.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_run_entries: List[Dict[str, Any]] = []


def reset_run_log() -> None:
    """Clear log entries for a new run."""
    _run_entries.clear()


def log_api_call(
    *,
    name: str,
    request_runtime: float | None,
    response_runtime: float | None = None,
    api_runtime: Optional[Dict[str, Any]] = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    llm_runtime: float | None = None,
) -> None:
    entry = {
        "type": "api",
        "name": name,
        "request_runtime": round(request_runtime or 0.0, 4),
    }
    if response_runtime is not None:
        entry["response_runtime"] = round(response_runtime, 4)
    if api_runtime:
        entry["api_runtime"] = api_runtime
    if input_tokens is not None:
        entry["input_token"] = input_tokens
    if output_tokens is not None:
        entry["output_token"] = output_tokens
    if llm_runtime is not None:
        entry["llm_runtime"] = round(llm_runtime, 4)
    _run_entries.append(entry)


def log_llm_call(
    *,
    name: str,
    input_tokens: int | None,
    output_tokens: int | None,
    llm_runtime: float | None,
) -> None:
    entry = {
        "type": "llm",
        "name": name,
        "input_token": input_tokens if input_tokens is not None else 0,
        "output_token": output_tokens if output_tokens is not None else 0,
        "llm_runtime": round(llm_runtime or 0.0, 4),
    }
    _run_entries.append(entry)


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
        "orchestrator_runtime": round(runtime_seconds, 4),
        "entries": list(_run_entries),
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

    if len(current) > 50:
        current = current[-50:]

    log_path.write_text(json.dumps(current, indent=2, ensure_ascii=False))


def write_response_log(
    *,
    path: str,
    name: str,
    payload: Any,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    entry = {
        "timestamp": int(time.time()),
        "name": name,
        "payload": payload,
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

    if len(current) > 50:
        current = current[-50:]

    log_path.write_text(json.dumps(current, indent=2, ensure_ascii=False))


def extract_runtime_log(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    candidates = [
        payload.get("runtime_log"),
        payload.get("log"),
        payload.get("runtime"),
        payload.get("metadata"),
        payload.get("meta"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            return candidate
        if isinstance(candidate, list) and candidate:
            return _summarize_log_entries(candidate)
        if isinstance(candidate, dict):
            nested = candidate.get("runtime_log") or candidate.get("log")
            if isinstance(nested, dict) and nested:
                return nested
    return {}


def parse_runtime_metrics(runtime_log: Dict[str, Any]) -> Dict[str, Any]:
    if not runtime_log:
        return {}
    metrics = {
        "input_token": _coerce_int(
            _get_value(
            runtime_log,
            ["input_token", "input_tokens", "prompt_token_count", "prompt_tokens"],
        ),
        ),
        "output_token": _coerce_int(
            _get_value(
            runtime_log,
            ["output_token", "output_tokens", "candidates_token_count", "completion_token_count"],
        ),
        ),
        "llm_runtime": _coerce_number(
            _get_value(
            runtime_log,
            ["llm_runtime", "llm_runtime_seconds", "llm_time", "llm_duration"],
        ),
        ),
        "response_runtime": _coerce_number(
            _get_value(
            runtime_log,
            [
                "response_runtime",
                "response_runtime_seconds",
                "response_time",
                "response_time_seconds",
            ],
        ),
        ),
        "api_runtime": _coerce_number(
            _get_value(
            runtime_log,
            ["api_runtime", "api_runtime_seconds", "runtime", "runtime_seconds"],
        ),
        ),
    }
    return {key: value for key, value in metrics.items() if value is not None}


def _get_value(usage_meta: Any, possible_keys: list[str]) -> Any | None:
    for key in possible_keys:
        if isinstance(usage_meta, dict) and key in usage_meta:
            return usage_meta[key]
        if hasattr(usage_meta, key):
            return getattr(usage_meta, key)
    return None


def _coerce_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_int(value: Any) -> int | None:
    number = _coerce_number(value)
    if number is None:
        return None
    return int(number)


def _summarize_log_entries(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    input_tokens = 0
    output_tokens = 0
    runtime_seconds = 0.0

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        input_tokens += _coerce_int(entry.get("input_token") or entry.get("input_tokens") or 0) or 0
        output_tokens += _coerce_int(entry.get("output_token") or entry.get("output_tokens") or 0) or 0
        runtime_seconds += _coerce_number(entry.get("runtime") or entry.get("runtime_seconds") or 0.0) or 0.0

    summarized: Dict[str, Any] = {}
    if input_tokens:
        summarized["input_token"] = input_tokens
    if output_tokens:
        summarized["output_token"] = output_tokens
    if runtime_seconds:
        summarized["llm_runtime"] = round(runtime_seconds, 4)
    return summarized
