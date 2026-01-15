from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from functions.config import (
    COURSE_RECOMMENDATION_API_BASE_URL,
    COURSE_RECOMMENDATION_PATH,
    DATA_GATHERING_API_BASE_URL,
    DATA_GATHERING_ATTEMPTS_PATH,
    DATA_GATHERING_QUESTIONS_PATH,
    GENERATION_MODEL,
    HTTP_TIMEOUT_SECONDS,
    RUN_LOG_PATH,
    RESPONSE_LOG_PATH,
    TEST_ANALYSIS_API_BASE_URL,
    TEST_ANALYSIS_PATH,
)
from functions.orchestrator.user_facing import generate_user_facing_response
from functions.utils.run_logging import (
    extract_runtime_log,
    log_api_call,
    parse_runtime_metrics,
    reset_run_log,
    write_run_log,
    write_response_log,
)


class OrchestratorService:
    def __init__(self) -> None:
        timeout = httpx.Timeout(HTTP_TIMEOUT_SECONDS)
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def orchestrate(
        self,
        *,
        student_id: str,
        test_id: str,
        max_courses: int,
        max_courses_per_weakness: int,
        participant_ranking: float = 0.0,
        language: str,
    ) -> Dict[str, Any]:
        run_id = f"run_{uuid.uuid4().hex}"
        reset_run_log()
        start = time.time()
        status = "ok"
        try:
            attempts = await self._fetch_attempts(student_id=student_id, test_id=test_id)
            current, history = _split_attempts(attempts)
            if not current:
                raise ValueError("No exam attempts found for student/test.")

            question_bank = await self._fetch_question_bank(test_id=test_id)
            question_lookup = {
                item.get("question", {}).get("id"): item
                for item in question_bank
                if item.get("question") and item.get("question", {}).get("id")
            }

            incorrect_cases, incorrect_summary = _build_incorrect_cases(
                current=current,
                question_lookup=question_lookup,
            )
            domain_performance = _compute_domain_performance(
                current=current,
                history=history,
                question_lookup=question_lookup,
            )

            if incorrect_summary["total_incorrect_questions"] == 0:
                participant_ranking_value = (
                    participant_ranking
                    if participant_ranking > 0
                    else _extract_participant_ranking(current)
                )
                user_response = generate_user_facing_response(
                    weaknesses=[],
                    recommendations=[],
                    test_result=_extract_exam_result(current),
                    history_result=_extract_exam_result(history) if history else None,
                    incorrect_summary=incorrect_summary,
                    all_correct=True,
                    participant_ranking=participant_ranking_value,
                    domain_performance=domain_performance,
                    language=language,
                )
                return {
                    "status": "all_correct",
                    "student_id": student_id,
                    "test_id": test_id,
                    "incorrect_summary": incorrect_summary,
                    "weaknesses": [],
                    "recommendations": [],
                    "user_facing_paragraph": user_response,
                }

            weaknesses = await self._fetch_weaknesses(incorrect_cases)
            limited_weaknesses = weaknesses[:5]
            recommendations = await self._fetch_recommendations(
                weaknesses=limited_weaknesses,
                max_courses=max_courses,
                max_courses_per_weakness=max_courses_per_weakness,
            )

            participant_ranking_value = (
                participant_ranking
                if participant_ranking > 0
                else _extract_participant_ranking(current)
            )
            user_response = generate_user_facing_response(
                weaknesses=limited_weaknesses,
                recommendations=recommendations,
                test_result=_extract_exam_result(current),
                history_result=_extract_exam_result(history) if history else None,
                incorrect_summary=incorrect_summary,
                all_correct=False,
                participant_ranking=participant_ranking_value,
                domain_performance=domain_performance,
                language=language,
            )

            return {
                "status": "ok",
                "student_id": student_id,
                "test_id": test_id,
                "incorrect_summary": incorrect_summary,
                "weaknesses": weaknesses,
                "recommendations": recommendations,
                "user_facing_paragraph": user_response,
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
                    "max_courses_per_weakness": max_courses_per_weakness,
                    "participant_ranking": participant_ranking,
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
        write_response_log(
            path=RESPONSE_LOG_PATH,
            name="data_gathering_attempts",
            payload=payload,
        )
        request_runtime = time.time() - start
        log_api_call(
            name="data_gathering_attempts",
            request_runtime=request_runtime,
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
        write_response_log(
            path=RESPONSE_LOG_PATH,
            name="data_gathering_questions",
            payload=payload,
        )
        request_runtime = time.time() - start
        log_api_call(
            name="data_gathering_questions",
            request_runtime=request_runtime,
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
        response = await self._client.post(url, json=payload, headers={"x-log": "true"})
        response.raise_for_status()
        data = response.json()
        write_response_log(
            path=RESPONSE_LOG_PATH,
            name="test_analysis",
            payload=data,
        )
        runtime_log = extract_runtime_log(data)
        runtime_metrics = parse_runtime_metrics(runtime_log)
        request_runtime = time.time() - start
        log_api_call(
            name="test_analysis",
            request_runtime=request_runtime,
            response_runtime=runtime_metrics.get("response_runtime", request_runtime),
            api_runtime=runtime_log or None,
            input_tokens=runtime_metrics.get("input_token"),
            output_tokens=runtime_metrics.get("output_token"),
            llm_runtime=runtime_metrics.get("llm_runtime"),
        )
        return data.get("weaknesses", [])

    async def _fetch_recommendations(
        self,
        *,
        weaknesses: List[Dict[str, Any]],
        max_courses: int,
        max_courses_per_weakness: int,
    ) -> List[Dict[str, Any]]:
        url = f"{COURSE_RECOMMENDATION_API_BASE_URL}{COURSE_RECOMMENDATION_PATH}"
        payload = {
            "weaknesses": weaknesses,
            "max_course": max_courses,
            "max_course_pr_weakness": max_courses_per_weakness,
        }
        start = time.time()
        response = await self._client.post(url, json=payload, headers={"include_log": "true"})
        response.raise_for_status()
        data = response.json()
        write_response_log(
            path=RESPONSE_LOG_PATH,
            name="course_recommendation",
            payload=data,
        )
        runtime_log = extract_runtime_log(data)
        runtime_metrics = parse_runtime_metrics(runtime_log)
        request_runtime = time.time() - start
        log_api_call(
            name="course_recommendation",
            request_runtime=request_runtime,
            response_runtime=runtime_metrics.get("response_runtime", request_runtime),
            api_runtime=runtime_log or None,
            input_tokens=runtime_metrics.get("input_token"),
            output_tokens=runtime_metrics.get("output_token"),
            llm_runtime=runtime_metrics.get("llm_runtime"),
        )
        return data.get("recommendations", [])


def _split_attempts(
    attempts: List[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not attempts:
        return None, None
    current = attempts[0]
    history = attempts[1] if len(attempts) > 1 else None
    return current, history


def _build_incorrect_cases(
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


def _extract_participant_ranking(source: Optional[Dict[str, Any]]) -> float:
    if not source:
        return 0.0
    exam_result = source.get("exam_result") if isinstance(source, dict) else None
    payload = exam_result if isinstance(exam_result, dict) else source
    for key in (
        "participantRanking",
        "participant_ranking",
        "participantRank",
        "participant_rank",
        "ranking",
        "rank",
    ):
        if key in payload:
            try:
                return float(payload.get(key))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _extract_exam_result(source: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not source:
        return None
    if not isinstance(source, dict):
        return None
    return source.get("exam_result") or source.get("examResult")


def _compute_domain_performance(
    *,
    current: Dict[str, Any],
    history: Optional[Dict[str, Any]],
    question_lookup: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "current": _compute_domain_stats(current, question_lookup),
        "history": _compute_domain_stats(history, question_lookup) if history else {},
    }


def _compute_domain_stats(
    attempt: Optional[Dict[str, Any]],
    question_lookup: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    if not attempt:
        return {}
    totals: Dict[str, int] = {}
    corrects: Dict[str, int] = {}

    for row in attempt.get("questions", []):
        question_id = row.get("questionId")
        question_info = question_lookup.get(question_id, {}).get("question", {})
        domain = question_info.get("domain") or "Unknown"
        answers = row.get("_answers", [])
        if not answers:
            continue
        is_correct = all(ans.get("isCorrect", False) for ans in answers)
        totals[domain] = totals.get(domain, 0) + 1
        if is_correct:
            corrects[domain] = corrects.get(domain, 0) + 1

    domains = []
    for domain, total in totals.items():
        if total <= 0:
            continue
        accuracy = corrects.get(domain, 0) / total
        domains.append(
            {
                "domain": domain,
                "accuracy": accuracy,
                "total": total,
                "correct": corrects.get(domain, 0),
            }
        )

    return {"domains": domains}
