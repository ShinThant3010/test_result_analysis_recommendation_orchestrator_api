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
    return {
        "current": compute_domain_stats(current),
        "history": compute_domain_stats(history) if history else {},
    }


# ---------------------------------------------------------------------------------------------
# Calculate statistics of a test result
# ---------------------------------------------------------------------------------------------
def compute_domain_stats(
    attempt: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not attempt:
        return {}

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
