from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from modules.utils.load_config import SETTINGS

DEFAULT_LANGUAGE = SETTINGS.defaults.language
DEFAULT_MAX_COURSES = SETTINGS.defaults.max_courses
DEFAULT_MAX_COURSES_PER_WEAKNESS = SETTINGS.defaults.max_courses_per_weakness


# ---------------------------------------------------------------------------------------------
# Request Payload Schema - Current Attempt
# ---------------------------------------------------------------------------------------------
class AnswerItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    answer_id: str = Field(
        ...,
        alias="answerId",
        description="Answer identifier.",
    )
    value: str = Field(
        ...,
        description="Answer text/value.",
    )


class AttemptQuestion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    test_result_question_id: str = Field(
        ...,
        alias="testResultQuestionId",
        description="Attempt question identifier.",
    )
    question_id: str = Field(
        ...,
        alias="questionId",
        description="Question identifier.",
    )
    question_text: str = Field(
        ...,
        alias="questionText",
        description="Question text.",
    )
    domain: str = Field(
        ...,
        description="Question domain/category.",
    )
    explanation: str | None = Field(
        None,
        description="Question explanation.",
    )
    correct_answers: list[AnswerItem] = Field(
        ...,
        alias="correctAnswers",
        description="List of correct answers (supports multi-answer).",
    )
    selected_answers: list[AnswerItem] = Field(
        ...,
        alias="selectedAnswers",
        description="List of selected student answers (supports multi-answer).",
    )
    is_correct: bool | None = Field(
        default=None,
        alias="isCorrect",
        description="Optional precomputed correctness flag.",
    )
    difficulty: str | None = Field(
        default=None,
        description="Optional question difficulty.",
    )
    score: float | None = Field(
        default=None,
        description="Optional question score.",
    )


class AttemptPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    earned_score: float | None = Field(
        default=None,
        alias="earnedScore",
        description="Earned score for this attempt.",
    )
    total_score: float | None = Field(
        default=None,
        alias="totalScore",
        description="Total score for this attempt.",
    )
    status: str | None = Field(
        default=None,
        description="Attempt status.",
    )
    questions: list[AttemptQuestion] = Field(
        ...,
        description="All MCQ questions for this attempt.",
    )


# ---------------------------------------------------------------------------------------------
# Request Payload Schema - Previous Attempt
# ---------------------------------------------------------------------------------------------
class PreviousAttemptDomainStat(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    domain: str = Field(
        ...,
        description="Question domain/category.",
    )
    correct_questions_count: int = Field(
        ...,
        alias="correctQuestionsCount",
        ge=0,
        description="Number of correct questions in the previous attempt for this domain.",
    )
    incorrect_questions_count: int = Field(
        ...,
        alias="incorrectQuestionsCount",
        ge=0,
        description="Number of incorrect questions in the previous attempt for this domain.",
    )


class PreviousAttemptPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    domains: list[PreviousAttemptDomainStat] = Field(
        ...,
        description="Domain-level score summary from the previous attempt.",
    )


# ---------------------------------------------------------------------------------------------
# Request Payload Schema - Core
# ---------------------------------------------------------------------------------------------
class OrchestrateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
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
    test_title: str = Field(
        ...,
        alias="testTitle",
        description="Test title displayed in user-facing output.",
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
        description="Maximum courses returned per weakness.",
    )
    participant_ranking: float | None = Field(
        default=None,
        alias="participantRanking",
        description="Optional fractional ranking (e.g., 0.317 => top 31.7%).",
    )
    language: str | None = Field(
        DEFAULT_LANGUAGE,
        alias="language",
        description="Output language for the final response (EN or TH).",
    )
    current_attempt: AttemptPayload = Field(
        ...,
        alias="currentAttempt",
        description="Current test attempt data.",
    )
    previous_attempt: PreviousAttemptPayload | list[PreviousAttemptDomainStat] | None = Field(
        default=None,
        alias="previousAttempt",
        description="Previous attempt domain summary, either as {domains:[...]} or a direct array.",
    )
