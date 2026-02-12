from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field

from functions.config import (
    DEFAULT_LANGUAGE,
    DEFAULT_MAX_COURSES,
    DEFAULT_MAX_COURSES_PER_WEAKNESS,
)


class OrchestrateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    exam_result_id: str = Field(
        ...,
        alias="examResultId",
        description="Exam result identifier.",
    )
    student_id: str = Field(
        ...,
        alias="studentId",
        description="Student identifier.",
    )
    test_id: str = Field(
        ...,
        alias="testId",
        description="Test identifier.",
    )
    max_courses: int = Field(
        DEFAULT_MAX_COURSES,
        alias="maxCourses",
        ge=1,
        description="Maximum total courses returned.",
    )
    max_courses_per_weakness: int = Field(
        DEFAULT_MAX_COURSES_PER_WEAKNESS,
        alias="maxCoursesPerWeakness",
        ge=1,
        description="Maximum courses per weakness.",
    )
    participant_ranking: float = Field(
        default=0.0,
        alias="participantRanking",
        description="Optional fractional ranking (e.g., 0.317 => top 31.7%).",
    )
    language: str = Field(
        DEFAULT_LANGUAGE,
        alias="language",
        description="Output language for the final response (EN or TH).",
    )


# Response models removed; API returns user_facing_paragraph as the full response body.
