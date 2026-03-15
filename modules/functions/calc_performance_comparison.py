from __future__ import annotations

from typing import Any, Dict, Optional

from modules.functions.check_correct_answers import is_question_correct


# ---------------------------------------------------------------------------------------------
# Performance Comparison of current & previous test
# ---------------------------------------------------------------------------------------------
def compute_domain_performance(
    *,
    current: Dict[str, Any],
    history: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute domain-level performance comparison between current and previous test attempts."""
    
    return {
        "current": compute_domain_stats(current),
        "history": compute_domain_stats(history) if history else {},
    }


# ---------------------------------------------------------------------------------------------
# Performance Comparison of each test
# ---------------------------------------------------------------------------------------------
def compute_domain_stats(
    attempt: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute domain-level performance statistics from a test attempt, including accuracy and total questions per domain."""
    
    if not attempt:
        return {}

    # catch for history data with domain-level stats
    domain_rows = attempt.get("domains", [])
    if isinstance(domain_rows, list) and domain_rows:
        domains = []
        for row in domain_rows:
            if not isinstance(row, dict):
                continue
            domain = row.get("domain") or "Unknown"
            correct = row.get("correct") or row.get("correct_questions_count") or 0
            incorrect = row.get("incorrect") or row.get("incorrect_questions_count") or 0
            try:
                correct_count = int(correct)
                incorrect_count = int(incorrect)
            except (TypeError, ValueError):
                continue
            total = correct_count + incorrect_count
            if total <= 0:
                continue
            domains.append(
                {
                    "domain": domain,
                    "accuracy": correct_count / total,
                    "total": total,
                    "correct": correct_count,
                }
            )
        return {"domains": domains}

    # catch for data without domain-level stats (compute from question-level data)
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
