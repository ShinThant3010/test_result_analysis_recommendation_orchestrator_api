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


async def fetch_recommendations(
    client: httpx.AsyncClient,
    *,
    weaknesses: List[Dict[str, Any]],
    max_courses: int,
    max_courses_per_weakness: int,
) -> List[Dict[str, Any]]:
    """Request course recommendations, filter low-score items, and log API metrics."""

    ### ---------------------- Request course recommendations ---------------------- ###
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
        response = await client.post(url, json=payload, headers={"include_log": "true"})
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"course_recommendation request failed: {exc}") from exc
    if response.status_code >= 400:
        raise RuntimeError(
            f"course_recommendation error: status={response.status_code} body={response.text}"
        )

    ### ------------------------- filter low-score items ------------------------- ###
    data = response.json()
    if isinstance(data, dict):
        data = {
            **data,
            "recommendations": filter_recommendations(
                data.get("recommendations", []),
                min_score=0.7,
            ),
        }

    ### ----------------------------- log API metrics ----------------------------- ###
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


def summarize_recommendations(recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only the user-facing recommendation fields needed downstream."""
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
        weakness = {key: weakness_data[key] for key in weakness_keys if key in weakness_data}
        courses = rec.get("recommendedCourses")
        if not isinstance(courses, list):
            courses = []
        summarized_courses = [
            {key: course[key] for key in course_keys if key in course}
            for course in courses
            if isinstance(course, dict)
        ]
        summarized.append(
            {
                "weakness": weakness,
                "recommendedCourses": [course for course in summarized_courses if course],
            }
        )
    return summarized


def filter_recommendations(
    recommendations: List[Dict[str, Any]],
    *,
    min_score: float,
) -> List[Dict[str, Any]]:
    """Remove recommended courses whose numeric score is at or below the threshold."""
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
