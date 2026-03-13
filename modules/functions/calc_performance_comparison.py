from __future__ import annotations

from typing import Any, Dict, Optional

from modules.functions.check_correct_answers import is_question_correct


def compute_domain_performance(
    *,
    current: Dict[str, Any],
    history: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "current": compute_domain_stats(current),
        "history": compute_domain_stats(history) if history else {},
    }


def compute_domain_stats(
    attempt: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not attempt:
        return {}

    domains_payload = attempt.get("domains")
    if isinstance(domains_payload, list):
        domains = []
        for row in domains_payload:
            if not isinstance(row, dict):
                continue
            domain = row.get("domain") or "Unknown"
            correct = coerce_nonnegative_int(row.get("correct_questions_count"))
            incorrect = coerce_nonnegative_int(row.get("incorrect_questions_count"))
            total = correct + incorrect
            if total <= 0:
                continue
            domains.append(
                {
                    "domain": domain,
                    "accuracy": correct / total,
                    "total": total,
                    "correct": correct,
                }
            )
        return {"domains": domains}

    totals: Dict[str, int] = {}
    corrects: Dict[str, int] = {}

    for row in attempt.get("questions", []):
        domain = row.get("domain") or "Unknown"
        is_correct = is_question_correct(row)
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


def coerce_nonnegative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)
