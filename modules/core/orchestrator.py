from __future__ import annotations

from dataclasses import dataclass
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

from modules.functions.analyze_weakness import fetch_weaknesses, summarize_weaknesses
from modules.functions.build_incorrect_cases import build_incorrect_cases
from modules.functions.calc_performance_comparison import compute_domain_performance
from modules.functions.generate_user_facing_response import (
    build_exam_result_payload,
    generate_user_facing_response,
)
from modules.functions.recommend_course import fetch_recommendations, summarize_recommendations
from modules.utils.load_config import SETTINGS
from modules.utils.run_logging import (
    reset_run_log,
    write_response_log,
    write_user_facing_log,
)

SERVICE_CONFIG = SETTINGS.service
LOGGING_CONFIG = SETTINGS.logging


# ---------------------------------------------------------------------------------------------
# Helper Class - Input Schema
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# Core - Test Result Analysis & Recommendation
# ---------------------------------------------------------------------------------------------
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

        ### -------------------------- prepare incorrect answers -------------------------- ###
            incorrect_cases, incorrect_summary = build_incorrect_cases(
                current=current,
            )
            print("# incorrect cases: ", len(incorrect_cases))

        ### --------------------- prepare for performance comparison --------------------- ###
            domain_performance = compute_domain_performance(
                current=current,
                history=history,
            )

        ### --------------------------- if no incorrect answers --------------------------- ###
            if incorrect_summary["total_incorrect_questions"] == 0:
                participant_ranking_value = (
                    data.participant_ranking
                    if data.participant_ranking and data.participant_ranking > 0
                    else 0.0
                )
                user_response = generate_user_facing_response(
                    weaknesses=[],
                    recommendations=[],
                    test_result=build_exam_result_payload(current, data.test_title),
                    history_result=build_exam_result_payload(history, data.test_title) if history else None,
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

        ### --------------------------- if no incorrect answers --------------------------- ###
            weaknesses = await fetch_weaknesses(self._client, incorrect_cases)
            test_analysis_output = summarize_weaknesses(weaknesses)
            print("weakness extraction success.")

            limited_weaknesses = weaknesses[:5]
            recommendations = await fetch_recommendations(
                self._client,
                weaknesses=limited_weaknesses,
                max_courses=data.max_courses,
                max_courses_per_weakness=data.max_courses_per_weakness,
            )
            course_recommendation_output = summarize_recommendations(recommendations)
            print("course recommendation success.")

            participant_ranking_value = (
                data.participant_ranking
                if data.participant_ranking and data.participant_ranking > 0
                else 0.0
            )
            user_response = generate_user_facing_response(
                weaknesses=limited_weaknesses,
                recommendations=recommendations,
                test_result=build_exam_result_payload(current, data.test_title),
                history_result=build_exam_result_payload(history, data.test_title) if history else None,
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

        ### --------------------------- save result in log --------------------------- ###
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
