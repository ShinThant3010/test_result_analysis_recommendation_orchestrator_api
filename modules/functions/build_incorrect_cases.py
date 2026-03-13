from __future__ import annotations

from typing import Any, Dict, List, Tuple

from modules.functions.check_correct_answers import is_question_correct


def build_incorrect_cases(
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
        is_correct = is_question_correct(row)
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
