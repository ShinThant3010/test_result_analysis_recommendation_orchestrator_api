from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx
from google import genai

from functions.utils.run_logging import (
    extract_token_counts,
    log_token_usage,
    reset_token_log,
    write_run_log,
)
from functions.config import (
    COURSE_RECOMMENDATION_API_BASE_URL,
    COURSE_RECOMMENDATION_PATH,
    DATA_GATHERING_API_BASE_URL,
    DATA_GATHERING_ATTEMPTS_PATH,
    DATA_GATHERING_QUESTIONS_PATH,
    DEFAULT_LANGUAGE,
    GENERATION_MODEL,
    HTTP_TIMEOUT_SECONDS,
    RUN_LOG_PATH,
    TEST_ANALYSIS_API_BASE_URL,
    TEST_ANALYSIS_PATH,
)


def _get_genai_client() -> genai.Client:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is missing")
    return genai.Client(api_key=api_key)


class OrchestratorService:
    def __init__(self) -> None:
        timeout = httpx.Timeout(HTTP_TIMEOUT_SECONDS)
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def orchestrate(
        self, *, student_id: str, test_id: str, max_courses: int, language: str
    ) -> Dict[str, Any]:
        run_id = f"run_{uuid.uuid4().hex}"
        reset_token_log()
        start = time.time()
        status = "ok"
        try:
            attempts = await self._fetch_attempts(student_id=student_id, test_id=test_id)
            current, history = self._split_attempts(attempts)
            if not current:
                raise ValueError("No exam attempts found for student/test.")

            question_bank = await self._fetch_question_bank(test_id=test_id)
            question_lookup = {
                item.get("question", {}).get("id"): item
                for item in question_bank
                if item.get("question") and item.get("question", {}).get("id")
            }

            incorrect_cases, incorrect_summary = self._build_incorrect_cases(
                current=current,
                question_lookup=question_lookup,
            )

            if incorrect_summary["total_incorrect_questions"] == 0:
                user_response = generate_user_facing_response(
                    weaknesses=[],
                    recommendations=[],
                    test_result=current.get("exam_result"),
                    history_result=history.get("exam_result") if history else None,
                    incorrect_summary=incorrect_summary,
                    all_correct=True,
                    language=language,
                )
                return {
                    "status": "all_correct",
                    "student_id": student_id,
                    "test_id": test_id,
                    "incorrect_summary": incorrect_summary,
                    "weaknesses": [],
                    "recommendations": [],
                    "user_facing_response": user_response,
                }

            weaknesses = await self._fetch_weaknesses(incorrect_cases)
            recommendations = await self._fetch_recommendations(
                weaknesses=weaknesses, max_courses=max_courses
            )

            user_response = generate_user_facing_response(
                weaknesses=weaknesses,
                recommendations=recommendations,
                test_result=current.get("exam_result"),
                history_result=history.get("exam_result") if history else None,
                incorrect_summary=incorrect_summary,
                all_correct=False,
                language=language,
            )

            return {
                "status": "ok",
                "student_id": student_id,
                "test_id": test_id,
                "incorrect_summary": incorrect_summary,
                "weaknesses": weaknesses,
                "recommendations": recommendations,
                "user_facing_response": user_response,
            }
        except Exception:
            status = "error"
            raise
        finally:
            runtime = time.time() - start
            write_run_log(
                path=RUN_LOG_PATH,
                run_id=run_id,
                status=status,
                runtime_seconds=runtime,
                metadata={
                    "student_id": student_id,
                    "test_id": test_id,
                    "max_courses": max_courses,
                    "language": language,
                },
            )

    async def _fetch_attempts(self, *, student_id: str, test_id: str) -> List[Dict[str, Any]]:
        url = (
            f"{DATA_GATHERING_API_BASE_URL}"
            + DATA_GATHERING_ATTEMPTS_PATH.format(student_id=student_id, test_id=test_id)
        )
        start = time.time()
        response = await self._client.get(url, params={"limit": 2})
        response.raise_for_status()
        payload = response.json()
        log_token_usage(
            "api:data_gathering_attempts",
            input_tokens=None,
            output_tokens=None,
            runtime_seconds=time.time() - start,
        )
        return payload.get("attempts", [])

    async def _fetch_question_bank(self, *, test_id: str) -> List[Dict[str, Any]]:
        url = (
            f"{DATA_GATHERING_API_BASE_URL}"
            + DATA_GATHERING_QUESTIONS_PATH.format(test_id=test_id)
        )
        start = time.time()
        response = await self._client.get(url)
        response.raise_for_status()
        payload = response.json()
        log_token_usage(
            "api:data_gathering_questions",
            input_tokens=None,
            output_tokens=None,
            runtime_seconds=time.time() - start,
        )
        return payload.get("questions", [])

    async def _fetch_weaknesses(
        self, incorrect_cases: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        url = f"{TEST_ANALYSIS_API_BASE_URL}{TEST_ANALYSIS_PATH}"
        payload = {
            "incorrect_cases": incorrect_cases,
            "model_name": GENERATION_MODEL,
        }
        start = time.time()
        response = await self._client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        log_token_usage(
            "api:test_analysis",
            input_tokens=None,
            output_tokens=None,
            runtime_seconds=time.time() - start,
        )
        return data.get("weaknesses", [])

    async def _fetch_recommendations(
        self, *, weaknesses: List[Dict[str, Any]], max_courses: int
    ) -> List[Dict[str, Any]]:
        url = f"{COURSE_RECOMMENDATION_API_BASE_URL}{COURSE_RECOMMENDATION_PATH}"
        payload = {"weaknesses": weaknesses, "max_courses": max_courses}
        start = time.time()
        response = await self._client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        log_token_usage(
            "api:course_recommendation",
            input_tokens=None,
            output_tokens=None,
            runtime_seconds=time.time() - start,
        )
        return data.get("recommendations", [])

    def _split_attempts(
        self, attempts: List[Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not attempts:
            return None, None
        current = attempts[0]
        history = attempts[1] if len(attempts) > 1 else None
        return current, history

    def _build_incorrect_cases(
        self,
        *,
        current: Dict[str, Any],
        question_lookup: Dict[str, Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        summary = {
            "total_questions_in_test": 0,
            "total_incorrect_questions": 0,
        }

        incorrect_cases: List[Dict[str, Any]] = []
        questions = current.get("questions", [])
        summary["total_questions_in_test"] = len(questions)

        for row in questions:
            answers = row.get("_answers", [])
            if not answers:
                continue
            any_incorrect = any(not ans.get("isCorrect", False) for ans in answers)
            if not any_incorrect:
                continue

            question_id = row.get("questionId")
            question_info = question_lookup.get(question_id, {}).get("question", {})
            answer_info = question_lookup.get(question_id, {}).get("answers", [])

            student_answers = [
                ans.get("answerValue") for ans in answers if ans.get("answerValue") is not None
            ]
            correct_answers = [
                ans.get("value") for ans in answer_info if ans.get("isCorrect") is True
            ]
            all_answers = [
                ans.get("value") for ans in answer_info if ans.get("value") is not None
            ]

            incorrect_cases.append(
                {
                    "questionId": question_id,
                    "testResultQuestionId": row.get("id"),
                    "questionText": question_info.get("question"),
                    "explanation": question_info.get("explanation"),
                    "studentAnswers": student_answers,
                    "correctAnswers": correct_answers,
                    "allAnswers": all_answers,
                    "difficulty": question_info.get("difficulty"),
                    "score": question_info.get("score"),
                }
            )

        summary["total_incorrect_questions"] = len(incorrect_cases)
        return incorrect_cases, summary


def generate_user_facing_response(
    *,
    weaknesses: List[Dict[str, Any]],
    recommendations: List[Dict[str, Any]],
    test_result: Optional[Dict[str, Any]],
    history_result: Optional[Dict[str, Any]],
    incorrect_summary: Dict[str, Any],
    all_correct: bool,
    language: str = DEFAULT_LANGUAGE,
) -> Dict[str, Any]:
    """
    LLM-based user-facing response, adapted from agent5_user_facing_response.py.
    """
    language_code = (language or DEFAULT_LANGUAGE).strip().upper()

    if all_correct:
        summary = {
            "Test Title": (test_result or {}).get("testTitle", ""),
            "Current Performance": "Congratulations on answering every question correctly!",
            "Area to be Improved": "",
            "Recommended Course": [],
            "Progress Compared to Previous Test": "",
            "Domain Comparison": [],
        }
        return {
            "summary": summary,
            "user_facing_paragraph": summary["Current Performance"],
            "recommendations": [],
        }

    weaknesses_text = "\n".join(
        f"- {w.get('weakness') or w.get('text') or w.get('description') or ''}"
        for w in weaknesses
    )

    flat_recs = _flatten_recommendations(recommendations)
    recs_text = "\n".join(
        f"- {rec.get('lesson_title') or rec.get('course_title') or ''}"
        for rec in flat_recs
    )

    prompt = f"""
You are generating a concise JSON report for a student based on weaknesses and recommended courses.

Full test result for the CURRENT attempt:
{json.dumps(test_result or {}, ensure_ascii=False, indent=2)}

Previous attempt (if any):
{json.dumps(history_result or {}, ensure_ascii=False, indent=2)}

Incorrect-question summary:
{json.dumps(incorrect_summary or {}, ensure_ascii=False, indent=2)}

Weaknesses identified:
{weaknesses_text}

Selected recommended courses (do NOT change this list):
{recs_text}

--- REQUIRED OUTPUT FORMAT (JSON ONLY) ---
{{
    "Test Title": "<the current test title>",
    "Current Performance": "<short paragraph summarizing current ability>",
    "Area to be Improved": "<short paragraph describing key skills to focus on>",
    "Recommended Course": [
        "<Course A explanation>",
        "<Course B explanation>",
        "..."
    ],
    "Progress Compared to Previous Test": "<if history exists, else empty string>",
    "Domain Comparison": [
        "<Domain A: Improved by +X%>",
        "<Domain B: Declined by -Y%>"
    ]
}}

--- TONE & FORMAT ---
- Use a supportive and encouraging tone.
- Keep each section concise (2-4 sentences).
- Base "Current Performance" on the provided test result and incorrect summary.
- Respond in the requested language: {language_code} (EN or TH). Keep JSON keys in English.
- Return ONLY valid JSON (no code fences, no commentary).
"""

    client = _get_genai_client()
    start = time.time()
    response = client.models.generate_content(
        model=GENERATION_MODEL,
        contents=[{"parts": [{"text": prompt}]}],
    )
    raw_text = (response.text or "").strip()
    input_tokens, output_tokens = extract_token_counts(response)
    log_token_usage(
        "llm:user_facing_response",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        runtime_seconds=time.time() - start,
    )
    summary_json = _parse_llm_json(raw_text)

    if not summary_json:
        summary_json = {
            "Test Title": (test_result or {}).get("testTitle", ""),
            "Current Performance": "We reviewed your performance and identified areas to improve.",
            "Area to be Improved": "Focus on the weaknesses detected in this attempt.",
            "Recommended Course": [rec.get("lesson_title") or "" for rec in flat_recs],
            "Progress Compared to Previous Test": "" if not history_result else "Progress compared to previous test",
            "Domain Comparison": [],
        }

    paragraph = _summary_to_paragraph(summary_json, flat_recs)
    return {
        "summary": summary_json,
        "user_facing_paragraph": paragraph,
        "recommendations": flat_recs,
    }


def _parse_llm_json(raw_text: str) -> Dict[str, Any]:
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        return {}
    return {}


def _flatten_recommendations(recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for entry in recommendations:
        for rec in entry.get("recommended_courses", []):
            flat.append(rec)
    return flat


def _summary_to_paragraph(summary_json: Dict[str, Any], recs: List[Dict[str, Any]]) -> str:
    parts = []
    title = summary_json.get("Test Title")
    if title:
        parts.append(f"[{title}]")
    current = summary_json.get("Current Performance")
    if current:
        parts.append(current)
    area = summary_json.get("Area to be Improved")
    if area:
        parts.append(area)
    if recs:
        rec_titles = ", ".join(
            rec.get("lesson_title") or rec.get("course_title") or "" for rec in recs
        )
        if rec_titles:
            parts.append(f"Recommended courses: {rec_titles}.")
    return " ".join(parts)
