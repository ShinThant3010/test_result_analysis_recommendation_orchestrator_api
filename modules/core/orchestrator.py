from __future__ import annotations

from dataclasses import dataclass
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from modules.utils.load_config import SETTINGS
from modules.core.user_facing import generate_user_facing_response
from modules.utils.run_logging import (
    extract_runtime_log,
    log_api_call,
    parse_runtime_metrics,
    reset_run_log,
    write_response_log,
    write_user_facing_log,
)

SERVICE_CONFIG = SETTINGS.service
LOGGING_CONFIG = SETTINGS.logging


@dataclass(frozen=True)
class OrchestrateInput:
    student_id: str
    test_id: str
    test_title: str
    max_courses: int
    max_courses_per_weakness: int
    participant_ranking: Optional[float]
    language: Optional[str]
    current_attempt: Dict[str, Any]
    previous_attempt: Optional[Dict[str, Any]]


class OrchestratorService:
    def __init__(self) -> None:
        timeout = httpx.Timeout(SERVICE_CONFIG.http_timeout_seconds)
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def orchestrate(self, data: OrchestrateInput) -> Dict[str, Any]:

        run_id = f"run_{uuid.uuid4().hex}"
        reset_run_log()
        start = time.time()
        status = "ok"

        test_analysis_output: Optional[Dict[str, Any]] = None
        course_recommendation_output: Optional[List[Dict[str, Any]]] = None
        user_facing_output: Optional[str] = None
        
        try:
            current = data.current_attempt
            history = data.previous_attempt
            if not current:
                raise ValueError("currentAttempt is required.")

            incorrect_cases, incorrect_summary = _build_incorrect_cases(
                current=current,
            )
            domain_performance = _compute_domain_performance(
                current=current,
                history=history,
            )

            if incorrect_summary["total_incorrect_questions"] == 0:
                participant_ranking_value = (
                    data.participant_ranking
                    if data.participant_ranking and data.participant_ranking > 0
                    else 0.0
                )
                user_response = generate_user_facing_response(
                    weaknesses=[],
                    recommendations=[],
                    test_result=_build_exam_result_payload(current, data.test_title),
                    history_result=_build_exam_result_payload(history, data.test_title) if history else None,
                    incorrect_summary=incorrect_summary,
                    all_correct=True,
                    participant_ranking=participant_ranking_value,
                    domain_performance=domain_performance,
                    language=data.language,
                )
                user_facing_output = user_response
                return {
                    "status": "all_correct",
                    "run_id": run_id,
                    "student_id": data.student_id,
                    "test_id": data.test_id,
                    "incorrect_summary": incorrect_summary,
                    "weaknesses": [],
                    "recommendations": [],
                    "user_facing_paragraph": user_response,
                }

            weaknesses = await self._fetch_weaknesses(incorrect_cases)
            test_analysis_output = _summarize_weaknesses(weaknesses)
            limited_weaknesses = weaknesses[:5]
            recommendations = await self._fetch_recommendations(
                weaknesses=limited_weaknesses,
                max_courses=data.max_courses,
                max_courses_per_weakness=data.max_courses_per_weakness,
            )
            course_recommendation_output = _summarize_recommendations(recommendations)

            participant_ranking_value = (
                data.participant_ranking
                if data.participant_ranking and data.participant_ranking > 0
                else 0.0
            )
            user_response = generate_user_facing_response(
                weaknesses=limited_weaknesses,
                recommendations=recommendations,
                test_result=_build_exam_result_payload(current, data.test_title),
                history_result=_build_exam_result_payload(history, data.test_title) if history else None,
                incorrect_summary=incorrect_summary,
                all_correct=False,
                participant_ranking=participant_ranking_value,
                domain_performance=domain_performance,
                language=data.language,
            )
            user_facing_output = user_response

            return {
                "status": "ok",
                "run_id": run_id,
                "student_id": data.student_id,
                "test_id": data.test_id,
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
            api_output: Dict[str, Any] = {
                "test_analysis": test_analysis_output or {"weaknesses": []},
                "course_recommendation": course_recommendation_output or [],
                "user_facing_response": user_facing_output or "",
            }
            write_response_log(
                path=LOGGING_CONFIG.response_log_path,
                run_id=run_id,
                status=status,
                runtime_seconds=runtime,
                api_output=api_output,
                metadata={
                    "student_id": data.student_id,
                    "test_id": data.test_id,
                    "test_title": data.test_title,
                    "max_courses": data.max_courses,
                    "max_courses_per_weakness": data.max_courses_per_weakness,
                    "participant_ranking": data.participant_ranking,
                    "language": data.language,
                },
            )
            if user_facing_output:
                write_user_facing_log(
                    path=LOGGING_CONFIG.user_facing_response_log_path,
                    run_id=run_id,
                    response=user_facing_output,
                )

    async def _fetch_weaknesses(
        self, incorrect_cases: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        url = f"{SERVICE_CONFIG.test_analysis_api_base_url}{SERVICE_CONFIG.test_analysis_path}"
        payload = {
            "incorrect_cases": incorrect_cases,
            "model_name": SERVICE_CONFIG.generation_model,
        }

        start = time.time()

        try:
            response = await self._client.post(url, json=payload, headers={"x-log": "true"})
        except Exception as exc:  # noqa: BLE001
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

    async def _fetch_recommendations(
        self,
        *,
        weaknesses: List[Dict[str, Any]],
        max_courses: int,
        max_courses_per_weakness: int,
    ) -> List[Dict[str, Any]]:
        url = (
            f"{SERVICE_CONFIG.course_recommendation_api_base_url}"
            f"{SERVICE_CONFIG.course_recommendation_path}"
        )
        payload = {
            "weaknesses": weaknesses,
            "max_course": max_courses,
            "max_course_pr_weakness": max_courses_per_weakness,
        }
        start = time.time()
        try:
            response = await self._client.post(url, json=payload, headers={"include_log": "true"})
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"course_recommendation request failed: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(
                f"course_recommendation error: status={response.status_code} body={response.text}"
            )
        data = response.json()
        if isinstance(data, dict):
            data = {
                **data,
                "recommendations": _filter_recommendations(
                    data.get("recommendations", []),
                    min_score=0.7,
                ),
            }
        runtime_log = extract_runtime_log(data)
        runtime_metrics = parse_runtime_metrics(runtime_log)
        request_runtime = time.time() - start
        api_log = runtime_log.get("log") if isinstance(runtime_log, dict) else None
        log_api_call(
            name="course_recommendation",
            request_runtime=request_runtime,
            api_runtime=api_log,
            input_tokens=runtime_metrics.get("input_token"),
            output_tokens=runtime_metrics.get("output_token"),
            llm_runtime=runtime_metrics.get("llm_runtime"),
        )
        return data.get("recommendations", [])

def _summarize_weaknesses(weaknesses: List[Dict[str, Any]]) -> Dict[str, Any]:
    keys = [
        "id",
        "weakness",
        "text",
        "description",
        "frequency",
        "evidenceQuestionIds",
    ]
    summarized = [_pick_keys(weakness, keys) for weakness in weaknesses if isinstance(weakness, dict)]
    return {"weaknesses": [item for item in summarized if item]}


def _summarize_recommendations(recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    weakness_keys = ["id", "weakness", "text", "description"]
    course_keys = [
        "courseId",
        "course_id",
        "lessonTitle",
        "lesson_title",
        "courseTitle",
        "course_title",
        "description",
        "link",
        "courseLink",
        "course_link",
        "score",
        "reason",
        "weaknessId",
    ]
    summarized: List[Dict[str, Any]] = []
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        weakness_data = rec.get("weakness", {})
        if not isinstance(weakness_data, dict):
            weakness_data = {}
        weakness = _pick_keys(weakness_data, weakness_keys)
        courses = rec.get("recommendedCourses")
        if not isinstance(courses, list):
            courses = []
        summarized_courses = [
            _pick_keys(course, course_keys) for course in courses if isinstance(course, dict)
        ]
        summarized.append(
            {
                "weakness": weakness,
                "recommendedCourses": [course for course in summarized_courses if course],
            }
        )
    return summarized


def _pick_keys(data: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    return {key: data[key] for key in keys if key in data}


def _filter_recommendations(
    recommendations: List[Dict[str, Any]],
    *,
    min_score: float,
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        courses = rec.get("recommendedCourses")
        if not isinstance(courses, list):
            filtered.append(rec)
            continue
        filtered_courses = []
        for course in courses:
            if not isinstance(course, dict):
                continue
            score = course.get("score")
            try:
                numeric_score = float(score) if score is not None else None
            except (TypeError, ValueError):
                numeric_score = None
            if numeric_score is not None and numeric_score <= min_score:
                continue
            filtered_courses.append(course)
        filtered.append({**rec, "recommendedCourses": filtered_courses})
    return filtered


def _build_incorrect_cases(
    *,
    current: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    summary = {
        "total_questions_in_test": 0,
        "total_incorrect_questions": 0,
    }

    incorrect_cases: List[Dict[str, Any]] = []
    questions = current.get("questions", [])
    summary["total_questions_in_test"] = len(questions)

    for row in questions:
        selected_answers = row.get("selected_answers", [])
        correct_answers = row.get("correct_answers", [])
        is_correct = _is_question_correct(row)
        if is_correct:
            continue

        student_answers = [
            ans.get("value") for ans in selected_answers if isinstance(ans, dict) and ans.get("value") is not None
        ]
        correct_answer_values = [
            ans.get("value") for ans in correct_answers if isinstance(ans, dict) and ans.get("value") is not None
        ]
        all_answers = list(dict.fromkeys([*correct_answer_values, *student_answers]))

        incorrect_cases.append(
            {
                "questionId": row.get("question_id"),
                "testResultQuestionId": row.get("test_result_question_id"),
                "questionText": row.get("question_text"),
                "explanation": row.get("explanation"),
                "studentAnswers": student_answers,
                "correctAnswers": correct_answer_values,
                "allAnswers": all_answers,
                "difficulty": row.get("difficulty"),
                "score": row.get("score"),
            }
        )

    summary["total_incorrect_questions"] = len(incorrect_cases)
    return incorrect_cases, summary

def _compute_domain_performance(
    *,
    current: Dict[str, Any],
    history: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "current": _compute_domain_stats(current),
        "history": _compute_domain_stats(history) if history else {},
    }


def _compute_domain_stats(
    attempt: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not attempt:
        return {}
    totals: Dict[str, int] = {}
    corrects: Dict[str, int] = {}

    for row in attempt.get("questions", []):
        domain = row.get("domain") or "Unknown"
        is_correct = _is_question_correct(row)
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


def _build_exam_result_payload(
    attempt: Optional[Dict[str, Any]],
    test_title: str,
) -> Optional[Dict[str, Any]]:
    if not attempt:
        return None
    payload: Dict[str, Any] = {"testTitle": test_title}
    if "earned_score" in attempt:
        payload["earnedScore"] = attempt.get("earned_score")
    if "total_score" in attempt:
        payload["totalScore"] = attempt.get("total_score")
    if "status" in attempt:
        payload["status"] = attempt.get("status")
    return payload


def _is_question_correct(question: Dict[str, Any]) -> bool:
    provided = question.get("is_correct")
    if isinstance(provided, bool):
        return provided
    selected = question.get("selected_answers", [])
    correct = question.get("correct_answers", [])
    return _answers_match(selected, correct)


def _answers_match(selected: List[Dict[str, Any]], correct: List[Dict[str, Any]]) -> bool:
    selected_ids = _answer_set(selected, key="answer_id")
    correct_ids = _answer_set(correct, key="answer_id")
    if selected_ids and correct_ids:
        return selected_ids == correct_ids

    selected_values = _answer_set(selected, key="value")
    correct_values = _answer_set(correct, key="value")
    if selected_values and correct_values:
        return selected_values == correct_values
    return False


def _answer_set(answers: List[Dict[str, Any]], *, key: str) -> set[str]:
    values = set()
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        value = answer.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            values.add(normalized)
    return values
