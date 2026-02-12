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
    RESPONSE_LOG_PATH,
    USER_FACING_RESPONSE_LOG_PATH,
    TEST_ANALYSIS_API_BASE_URL,
    TEST_ANALYSIS_PATH,
)
from functions.orchestrator.user_facing import generate_user_facing_response
from functions.utils.run_logging import (
    extract_runtime_log,
    log_api_call,
    parse_runtime_metrics,
    reset_run_log,
    write_response_log,
    write_user_facing_log,
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
        exam_result_id: str,
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
        test_analysis_output: Optional[Dict[str, Any]] = None
        course_recommendation_output: Optional[List[Dict[str, Any]]] = None
        user_facing_output: Optional[str] = None
        try:
            attempts = await self._fetch_attempts(exam_result_id=exam_result_id, student_id=student_id, test_id=test_id)
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
                user_facing_output = user_response
                return {
                    "status": "all_correct",
                    "run_id": run_id,
                    "student_id": student_id,
                    "test_id": test_id,
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
                max_courses=max_courses,
                max_courses_per_weakness=max_courses_per_weakness,
            )
            course_recommendation_output = _summarize_recommendations(recommendations)

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
            user_facing_output = user_response

            return {
                "status": "ok",
                "run_id": run_id,
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
            api_output: Dict[str, Any] = {
                "test_analysis": test_analysis_output or {"weaknesses": []},
                "course_recommendation": course_recommendation_output or [],
                "user_facing_response": user_facing_output or "",
            }
            write_response_log(
                path=RESPONSE_LOG_PATH,
                run_id=run_id,
                status=status,
                runtime_seconds=runtime,
                api_output=api_output,
                metadata={
                    "student_id": student_id,
                    "test_id": test_id,
                    "max_courses": max_courses,
                    "max_courses_per_weakness": max_courses_per_weakness,
                    "participant_ranking": participant_ranking,
                    "language": language,
                },
            )
            if user_facing_output:
                write_user_facing_log(
                    path=USER_FACING_RESPONSE_LOG_PATH,
                    run_id=run_id,
                    response=user_facing_output,
                )

    async def _fetch_attempts(self, *, exam_result_id: str, student_id: str, test_id: str) -> List[Dict[str, Any]]:
        url = (
            f"{DATA_GATHERING_API_BASE_URL}"
            + DATA_GATHERING_ATTEMPTS_PATH.format(exam_result_id=exam_result_id, student_id=student_id, test_id=test_id)
        )
        start = time.time()
        try:
            response = await self._client.get(url, params={"limit": 2})
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"data_gathering_attempts request failed: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(
                f"data_gathering_attempts error: status={response.status_code} body={response.text}"
            )
        payload = response.json()
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
        try:
            response = await self._client.get(url)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"data_gathering_questions request failed: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(
                f"data_gathering_questions error: status={response.status_code} body={response.text}"
            )
        payload = response.json()
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

        data = _remove_importance(response.json())
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
        url = f"{COURSE_RECOMMENDATION_API_BASE_URL}{COURSE_RECOMMENDATION_PATH}"
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
        data = _remove_importance(response.json())
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


def _split_attempts(
    attempts: List[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not attempts:
        return None, None
    current = attempts[0]
    history = attempts[1] if len(attempts) > 1 else None
    return current, history


def _remove_importance(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_importance(val)
            for key, val in value.items()
            if key not in ("importance", "patternType", "pattern_type")
        }
    if isinstance(value, list):
        return [_remove_importance(item) for item in value]
    return value


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
