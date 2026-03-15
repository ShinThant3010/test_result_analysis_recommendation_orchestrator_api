from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PAYLOAD_DIR = BASE_DIR / "example_payload"
REGION = os.getenv("LOCATION") or os.getenv("REGION") or "asia-southeast1"
API_URL = os.getenv(
    "TEST_API_URL",
    "http://127.0.0.1:8080/v1/orchestrator/test-result-analysis-and-recommendations",
)
API_VERSION = os.getenv("TEST_API_VERSION", "1")
API_BEARER_TOKEN = ""
TIMEOUT_SECONDS = float(os.getenv("TEST_API_TIMEOUT_SECONDS", "120"))

# Set specific student IDs here when you want to limit which payloads are sent.
TARGET_STUDENT_IDS: list[str] = ["STUDENT_A", "STUDENT_B", "STUDENT_C", "STUDENT_D", "STUDENT_E"]


def load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def call_test_api(payload: dict[str, Any], *, correlation_id: str | None = None) -> httpx.Response:
    headers = {
        "Content-Type": "application/json",
        "X-API-Version": API_VERSION,
    }
    if correlation_id:
        headers["X-Correlation-Id"] = correlation_id
    if API_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {API_BEARER_TOKEN}"

    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        response = client.post(API_URL, json=payload, headers=headers)
    return response


def test_payload_file(path: Path) -> httpx.Response:
    payload = load_payload(path)
    correlation_id = f"test-{path.stem}"
    return call_test_api(payload, correlation_id=correlation_id)


def loop_test_payloads(student_ids: list[str] | None = None) -> list[tuple[Path, httpx.Response]]:
    student_ids = [student_id for student_id in (student_ids or []) if student_id]
    allowed_student_ids = set(student_ids)
    paths = sorted(PAYLOAD_DIR.glob("*.json"))

    results: list[tuple[Path, httpx.Response]] = []
    for path in paths:
        payload = load_payload(path)
        if allowed_student_ids and payload.get("studentId") not in allowed_student_ids:
            continue
        response = call_test_api(payload, correlation_id=f"test-{path.stem}")
        results.append((path, response))
    return results


def main() -> None:
    results = loop_test_payloads(TARGET_STUDENT_IDS)
    for path, response in results:
        print(f"{path.name}: {response.status_code}")
        print(response.text)


if __name__ == "__main__":
    main()
