from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

try:
    from google.cloud import bigquery
except ImportError as exc: 
    raise SystemExit(
        "Missing dependency: google-cloud-bigquery. Install it before running this script."
    ) from exc


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "example_payload"

REGION = os.getenv("LOCATION") or os.getenv("REGION") or "asia-southeast1"
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID") or os.getenv("BQ_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""
BQ_DATASET = os.getenv("BIGQUERY_DATASET") or os.getenv("BQ_DATASET") or ""
QUESTION_TABLE = os.getenv("BQ_QUESTION_TABLE", "question")
ANSWER_TABLE = os.getenv("BQ_ANSWER_TABLE", "answer")
EXAM_RESULT_TABLE = os.getenv("BQ_EXAM_RESULT_TABLE", "exam_result")
EXAM_QUESTION_RESULT_TABLE = os.getenv("BQ_EXAM_QUESTION_RESULT_TABLE", "exam_question_result")
EXAM_ANSWER_RESULT_TABLE = os.getenv("BQ_EXAM_ANSWER_RESULT_TABLE", "exam_answer_result")
DEFAULT_MAX_COURSES = int(os.getenv("DEFAULT_MAX_COURSES", "5"))
DEFAULT_MAX_COURSES_PER_WEAKNESS = int(os.getenv("DEFAULT_MAX_COURSES_PER_WEAKNESS", "3"))
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "EN")

# Set to specific IDs when you want to limit payload generation.
TARGET_STUDENT_IDS: list[str] = ["STUDENT_A", "STUDENT_B", "STUDENT_C", "STUDENT_D", "STUDENT_E"]


def _require_env(value: str, name: str) -> str:
    if value.strip():
        return value.strip()
    raise ValueError(f"Missing required environment variable: {name}")


def _table_ref(table_name: str) -> str:
    project_id = _require_env(GCP_PROJECT_ID, "GCP_PROJECT_ID, BQ_PROJECT_ID or GOOGLE_CLOUD_PROJECT")
    dataset = _require_env(BQ_DATASET, "BIGQUERY_DATASET or BQ_DATASET")
    return f"`{project_id}.{dataset}.{table_name}`"


def _client() -> bigquery.Client:
    return bigquery.Client(
        project=_require_env(GCP_PROJECT_ID, "GCP_PROJECT_ID, BQ_PROJECT_ID or GOOGLE_CLOUD_PROJECT"),
        location=REGION,
    )


def fetch_latest_exam_results(
    client: bigquery.Client,
    student_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter] = []
    student_ids = [student_id for student_id in (student_ids or []) if student_id]
    if student_ids:
        filters.append("user_id IN UNNEST(@student_ids)")
        params.append(bigquery.ArrayQueryParameter("student_ids", "STRING", student_ids))

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    query = f"""
        WITH ranked AS (
          SELECT
            id,
            user_id,
            test_id,
            test_title,
            attempt_number,
            total_attempts,
            earned_score,
            total_score,
            status,
            created_at,
            ROW_NUMBER() OVER (
              PARTITION BY user_id, test_id
              ORDER BY created_at DESC, attempt_number DESC, id DESC
            ) AS row_num
          FROM {_table_ref(EXAM_RESULT_TABLE)}
          {where_clause}
        )
        SELECT
          id,
          user_id,
          test_id,
          test_title,
          attempt_number,
          total_attempts,
          earned_score,
          total_score,
          status,
          created_at
        FROM ranked
        WHERE row_num = 1
        ORDER BY user_id, test_id
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    rows = client.query(query, job_config=job_config).result()
    return [dict(row.items()) for row in rows]


def fetch_attempt_questions(client: bigquery.Client, exam_result_id: str) -> list[dict[str, Any]]:
    query = f"""
        SELECT
          eqr.id AS test_result_question_id,
          eqr.question_id AS question_id,
          eqr.created_at AS exam_question_created_at,
          q.question AS question_text,
          q.domain AS domain,
          q.explanation AS explanation,
          q.score AS score,
          q.created_at AS question_created_at,
          q.status AS question_status,
          ear.answer_id AS selected_answer_id,
          ear.answer_value AS selected_answer_value,
          ear.is_correct AS selected_answer_is_correct,
          ear.created_at AS selected_answer_created_at,
          a.id AS correct_answer_id,
          a.value AS correct_answer_value,
          a.order AS correct_answer_order
        FROM {_table_ref(EXAM_QUESTION_RESULT_TABLE)} AS eqr
        JOIN {_table_ref(QUESTION_TABLE)} AS q
          ON q.id = eqr.question_id
        LEFT JOIN {_table_ref(EXAM_ANSWER_RESULT_TABLE)} AS ear
          ON ear.exam_result_question_id = eqr.id
        LEFT JOIN {_table_ref(ANSWER_TABLE)} AS a
          ON a.question_id = eqr.question_id
         AND a.is_correct = TRUE
        WHERE eqr.exam_result_id = @exam_result_id
        ORDER BY eqr.created_at, eqr.id, a.order, a.id, ear.created_at, ear.id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("exam_result_id", "STRING", exam_result_id)]
    )
    rows = client.query(query, job_config=job_config).result()
    return [dict(row.items()) for row in rows]


def fetch_previous_exam_result(
    client: bigquery.Client,
    *,
    user_id: str,
    test_id: str,
    current_attempt_number: int | None,
    current_created_at: Any,
) -> dict[str, Any] | None:
    query = f"""
        SELECT
          id,
          user_id,
          test_id,
          test_title,
          attempt_number,
          total_attempts,
          earned_score,
          total_score,
          status,
          created_at
        FROM {_table_ref(EXAM_RESULT_TABLE)}
        WHERE user_id = @user_id
          AND test_id = @test_id
          AND (
            (attempt_number IS NOT NULL AND @current_attempt_number IS NOT NULL AND attempt_number < @current_attempt_number)
            OR (created_at < @current_created_at)
          )
        ORDER BY attempt_number DESC, created_at DESC, id DESC
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("test_id", "STRING", test_id),
            bigquery.ScalarQueryParameter("current_attempt_number", "INT64", current_attempt_number),
            bigquery.ScalarQueryParameter("current_created_at", "TIMESTAMP", current_created_at),
        ]
    )
    rows = list(client.query(query, job_config=job_config).result())
    if not rows:
        return None
    return dict(rows[0].items())


def _dedupe_answers(answers: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for answer in answers:
        answer_id = str(answer.get("answerId") or "").strip()
        value = str(answer.get("value") or "").strip()
        key = (answer_id, value)
        if not value or key in seen:
            continue
        seen.add(key)
        deduped.append({"answerId": answer_id, "value": value})
    return deduped


def _normalized_answer_set(answers: Iterable[dict[str, Any]], key: str) -> set[str]:
    values: set[str] = set()
    for answer in answers:
        value = answer.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            values.add(normalized)
    return values


def _question_is_correct(
    selected_answers: list[dict[str, Any]],
    correct_answers: list[dict[str, Any]],
) -> bool:
    # Prefer answer text/value because this dataset can contain inconsistent
    # answer IDs between stored answer results and the answer master table.
    selected_values = _normalized_answer_set(selected_answers, "value")
    correct_values = _normalized_answer_set(correct_answers, "value")
    if selected_values and correct_values:
        return selected_values == correct_values

    selected_ids = _normalized_answer_set(selected_answers, "answerId")
    correct_ids = _normalized_answer_set(correct_answers, "answerId")
    if selected_ids and correct_ids:
        return selected_ids == correct_ids

    return False


def build_current_attempt(rows: list[dict[str, Any]], exam_result: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in rows:
        question_key = str(row["test_result_question_id"])
        question_payload = grouped.setdefault(
            question_key,
            {
                "testResultQuestionId": row["test_result_question_id"],
                "questionId": row["question_id"],
                "questionText": row.get("question_text"),
                "domain": row.get("domain"),
                "explanation": row.get("explanation"),
                "difficulty": None,
                "score": row.get("score"),
                "_selectedAnswers": [],
                "_correctAnswers": [],
            },
        )

        if row.get("selected_answer_id") or row.get("selected_answer_value"):
            question_payload["_selectedAnswers"].append(
                {
                    "answerId": row.get("selected_answer_id"),
                    "value": row.get("selected_answer_value"),
                }
            )
        if row.get("correct_answer_id") or row.get("correct_answer_value"):
            question_payload["_correctAnswers"].append(
                {
                    "answerId": row.get("correct_answer_id"),
                    "value": row.get("correct_answer_value"),
                }
            )

    questions: list[dict[str, Any]] = []
    for question_payload in grouped.values():
        selected_answers = _dedupe_answers(question_payload.pop("_selectedAnswers"))
        correct_answers = _dedupe_answers(question_payload.pop("_correctAnswers"))
        question_payload["selectedAnswers"] = selected_answers
        question_payload["correctAnswers"] = correct_answers
        question_payload["isCorrect"] = _question_is_correct(selected_answers, correct_answers)
        questions.append(question_payload)

    return {
        "earnedScore": exam_result.get("earned_score"),
        "totalScore": exam_result.get("total_score"),
        "status": exam_result.get("status"),
        "questions": questions,
    }


def build_previous_attempt(rows: list[dict[str, Any]], exam_result: dict[str, Any]) -> dict[str, Any]:
    current_attempt = build_current_attempt(rows, exam_result)
    domain_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "incorrect": 0})

    for question in current_attempt["questions"]:
        domain = question.get("domain") or "Unknown"
        if question.get("isCorrect"):
            domain_counts[domain]["correct"] += 1
        else:
            domain_counts[domain]["incorrect"] += 1

    domains = [
        {
            "domain": domain,
            "correctQuestionsCount": counts["correct"],
            "incorrectQuestionsCount": counts["incorrect"],
        }
        for domain, counts in sorted(domain_counts.items())
    ]
    return {"domains": domains}


def build_payload(
    client: bigquery.Client,
    exam_result: dict[str, Any],
) -> dict[str, Any]:
    current_rows = fetch_attempt_questions(client, str(exam_result["id"]))
    previous_exam_result = fetch_previous_exam_result(
        client,
        user_id=str(exam_result["user_id"]),
        test_id=str(exam_result["test_id"]),
        current_attempt_number=exam_result.get("attempt_number"),
        current_created_at=exam_result.get("created_at"),
    )

    payload = {
        "studentId": exam_result["user_id"],
        "testId": exam_result["test_id"],
        "testTitle": exam_result.get("test_title"),
        "maxCourses": DEFAULT_MAX_COURSES,
        "maxCoursesPerWeakness": DEFAULT_MAX_COURSES_PER_WEAKNESS,
        "participantRanking": None,
        "language": DEFAULT_LANGUAGE,
        "currentAttempt": build_current_attempt(current_rows, exam_result),
        "previousAttempt": None,
    }

    if previous_exam_result:
        previous_rows = fetch_attempt_questions(client, str(previous_exam_result["id"]))
        payload["previousAttempt"] = build_previous_attempt(previous_rows, previous_exam_result)

    return payload


def save_payload(payload: dict[str, Any], output_dir: Path = OUTPUT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    student_id = str(payload["studentId"])
    test_id = str(payload["testId"])
    file_path = output_dir / f"{student_id}_{test_id}.json"
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return file_path


def generate_payload_files(student_ids: Iterable[str] | None = None) -> list[Path]:
    client = _client()
    exam_results = fetch_latest_exam_results(client, student_ids=student_ids)
    output_paths: list[Path] = []
    for exam_result in exam_results:
        payload = build_payload(client, exam_result)
        output_paths.append(save_payload(payload))
    return output_paths


def main() -> None:
    paths = generate_payload_files(TARGET_STUDENT_IDS)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
