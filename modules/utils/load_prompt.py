from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any

import yaml


@lru_cache(maxsize=1)
def _load_prompts(path: str = "modules/parameters/prompts.yaml") -> dict[str, str]:
    prompt_path = Path(path)
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    with prompt_path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}

    if not isinstance(payload, dict):
        raise ValueError(f"Invalid prompt format in {prompt_path}: expected mapping at root.")

    normalized: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            normalized[str(key)] = value
    return normalized


def get_prompt(name: str) -> str:
    prompts = _load_prompts()
    if name not in prompts:
        raise KeyError(f"Prompt key not found: {name}")
    return prompts[name]


def render_prompt(name: str, values: dict[str, Any]) -> str:
    template = Template(get_prompt(name))
    str_values = {key: str(value) for key, value in values.items()}
    return template.safe_substitute(str_values)
