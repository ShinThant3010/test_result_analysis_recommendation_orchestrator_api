from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------------------------
# Check if selected & correct answers are matched
# ---------------------------------------------------------------------------------------------
def is_question_correct(question: Dict[str, Any]) -> bool:
    provided = question.get("is_correct")
    if isinstance(provided, bool):
        return provided
    selected = question.get("selected_answers", [])
    correct = question.get("correct_answers", [])
    return answers_match(selected, correct)


def answers_match(selected: List[Dict[str, Any]], correct: List[Dict[str, Any]]) -> bool:
    selected_ids = answer_set(selected, key="answer_id")
    correct_ids = answer_set(correct, key="answer_id")
    if selected_ids and correct_ids:
        return selected_ids == correct_ids

    selected_values = answer_set(selected, key="value")
    correct_values = answer_set(correct, key="value")
    if selected_values and correct_values:
        return selected_values == correct_values
    return False


def answer_set(answers: List[Dict[str, Any]], *, key: str) -> set[str]:
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
