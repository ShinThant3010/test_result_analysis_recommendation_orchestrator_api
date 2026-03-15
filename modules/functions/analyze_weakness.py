from __future__ import annotations

import time
from typing import Any, Dict, List

import httpx

from modules.utils.load_config import SETTINGS
from modules.utils.run_logging import (
    extract_runtime_log,
    log_api_call,
    parse_runtime_metrics,
)

SERVICE_CONFIG = SETTINGS.service


# ---------------------------------------------------------------------------------------------
# Fetch weaknesses via internal api - test result analysis
# ---------------------------------------------------------------------------------------------
async def fetch_weaknesses(
    client: httpx.AsyncClient,
    incorrect_cases: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Fetch weaknesses from the test analysis API based on the provided incorrect cases."""

    url = f"{SERVICE_CONFIG.test_analysis_api_base_url}{SERVICE_CONFIG.test_analysis_path}"
    payload = {
        "incorrect_cases": incorrect_cases,
        "model_name": SERVICE_CONFIG.generation_model,
    }

    start = time.time()

    ### --------------------------- [api call] test result analysis --------------------------- ###
    try:
        response = await client.post(url, json=payload, headers={"x-log": "true"})
    except Exception as exc: 
        raise RuntimeError(
            f"test_analysis_api request failed: {type(exc).__name__}: {exc!r}"
        ) from exc
    if response.status_code >= 400:
        response_text = response.text
        raise RuntimeError(
            f"test_analysis_api error: status={response.status_code} body={response_text}"
        )

    data = response.json()
    weaknesses = data.get("weaknesses", []) if isinstance(data, dict) else []

    ### --------------------------- extract log data --------------------------- ###
    runtime_log = extract_runtime_log(data)
    runtime_metrics = parse_runtime_metrics(runtime_log)
    request_runtime = time.time() - start
    api_log = runtime_log.get("log") if isinstance(runtime_log, dict) else None
    log_api_call(
        name="test_analysis",
        request_runtime=request_runtime,
        api_runtime=api_log,
        input_tokens=runtime_metrics.get("input_token"),
        output_tokens=runtime_metrics.get("output_token"),
        llm_runtime=runtime_metrics.get("llm_runtime"),
    )
    return weaknesses


# ---------------------------------------------------------------------------------------------
# Helper Class - Format weaknesses
# ---------------------------------------------------------------------------------------------
def summarize_weaknesses(weaknesses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize the weaknesses by extracting relevant fields."""

    keys = [
        "id",
        "weakness",
        "text",
        "description",
        "frequency",
        "evidenceQuestionIds",
    ]
    summarized = [{key: weakness[key] for key in keys if key in weakness} for weakness in weaknesses if isinstance(weakness, dict)]
    return {"weaknesses": [item for item in summarized if item]}
