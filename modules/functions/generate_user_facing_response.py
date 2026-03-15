from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from modules.utils.load_config import SETTINGS
from modules.utils.llm import generate_content_with_logging
from modules.utils.load_prompt import render_prompt

DEFAULT_LANGUAGE = SETTINGS.defaults.language
GENERATION_MODEL = SETTINGS.service.generation_model


# ---------------------------------------------------------------------------------------------
# Helper function - Construct data for test_result, history_result for response text
# ---------------------------------------------------------------------------------------------
def build_exam_result_payload(
    attempt: Optional[Dict[str, Any]],
    test_title: str,
) -> Optional[Dict[str, Any]]:
    if not attempt:
        return None
    payload: Dict[str, Any] = {"testTitle": test_title}
    if "earned_score" in attempt:
        payload["earnedScore"] = attempt.get("earned_score")
    if "total_score" in attempt:
        payload["totalScore"] = attempt.get("total_score")
    if "status" in attempt:
        payload["status"] = attempt.get("status")
    return payload


# ---------------------------------------------------------------------------------------------
# Core function - format response
# ---------------------------------------------------------------------------------------------
def generate_user_facing_response(
    *,
    weaknesses: List[Dict[str, Any]],
    recommendations: List[Dict[str, Any]],
    test_result: Optional[Dict[str, Any]],
    history_result: Optional[Dict[str, Any]],
    incorrect_summary: Dict[str, Any],
    all_correct: bool,
    participant_ranking: float = 0.0,
    domain_performance: Optional[Dict[str, Any]] = None,
    language: str = DEFAULT_LANGUAGE,
) -> str:
    language_code = (language or DEFAULT_LANGUAGE).strip().upper()

    ### -------------------------- participant ranking -------------------------- ###
    ranking_sentence_text = _format_ranking(
        participant_ranking, language_code=language_code, mode="sentence"
    )

    ### -------------------------- response header -------------------------- ###
    progress_heading_text = _progress_heading(test_result, history_result)

    weaknesses_text = "\n".join(
        f"- {w.get('weakness') or w.get('text') or w.get('description') or ''}"
        for w in weaknesses
    )

    ### ---------------------- prep recommendation list ---------------------- ###
    flat_recs = _flatten_recommendations(recommendations)
    if all_correct:
        flat_recs = []
    recs_text = "\n".join(
        f"- {rec.get('lessonTitle') or rec.get('lesson_title') or rec.get('courseTitle') or rec.get('course_title') or ''}"
        for rec in flat_recs
    )

    ranking_text = _format_ranking(
        participant_ranking, language_code=language_code, mode="prompt"
    )
    progress_heading_prompt = progress_heading_text or "N/A"

    prompt = render_prompt(
        "generate_user_facing_response",
        {
            "test_result_json": json.dumps(test_result or {}, ensure_ascii=False, indent=2),
            "history_result_json": json.dumps(history_result or {}, ensure_ascii=False, indent=2),
            "incorrect_summary_json": json.dumps(incorrect_summary or {}, ensure_ascii=False, indent=2),
            "ranking_text": ranking_text,
            "progress_heading_prompt": progress_heading_prompt,
            "domain_performance_json": json.dumps(domain_performance or {}, ensure_ascii=False, indent=2),
            "all_correct": all_correct,
            "weaknesses_text": weaknesses_text,
            "recs_text": recs_text or "N/A",
            "language_code": language_code,
        },
    )

    raw_text = generate_content_with_logging(
        model=GENERATION_MODEL,
        prompt=prompt,
        log_name="user_facing_response",
    )
    summary_json = _parse_llm_json(raw_text)
    summary_json = non_llm_summary(
        summary_json=summary_json,
        all_correct=all_correct,
        language_code=language_code,
        ranking_sentence_text=ranking_sentence_text,
        test_result=test_result,
        progress_heading_text=progress_heading_text,
        flat_recs=flat_recs,
        history_result=history_result,
        domain_performance=domain_performance,
    )

    paragraph = _summary_to_paragraph(summary_json, flat_recs)
    return paragraph


def non_llm_summary(
    *,
    summary_json: Dict[str, Any],
    all_correct: bool,
    language_code: str,
    ranking_sentence_text: str,
    test_result: Optional[Dict[str, Any]],
    progress_heading_text: str,
    flat_recs: List[Dict[str, Any]],
    history_result: Optional[Dict[str, Any]],
    domain_performance: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not summary_json:
        if all_correct:
            if language_code == "TH":
                current_perf = "คุณตอบถูกทุกข้อ แสดงให้เห็นถึงความเข้าใจที่แข็งแกร่งมาก"
                next_steps = (
                    "ลองทำแบบทดสอบระดับสูงขึ้นหรือโจทย์ประยุกต์ที่เกี่ยวข้องกับหัวข้อเดียวกัน "
                    "เพื่อขยายความเชี่ยวชาญไปสู่แนวคิดขั้นสูง"
                )
            else:
                current_perf = "You answered every question correctly, showing strong mastery."
                next_steps = (
                    "Try an advanced-level version of this test or applied problems in the same topic "
                    "to deepen your understanding of higher-level concepts."
                )
            if ranking_sentence_text:
                current_perf = f"{current_perf} {ranking_sentence_text}"
            summary_json = {
                "Test Title": (test_result or {}).get("testTitle", ""),
                "Current Performance": current_perf,
                "Area to be Improved": "",
                "Next Steps to Explore": next_steps,
                "Recommended Course": [],
                "Progress Compared to Previous Test": progress_heading_text,
                "Domain Comparison": [],
            }
        else:
            current_perf = (
                "We reviewed your performance and identified areas to improve. "
                "Focus on practicing the weakest topics and reviewing core concepts to build accuracy."
            )
            if ranking_sentence_text:
                current_perf = f"{current_perf} {ranking_sentence_text}"
            summary_json = {
                "Test Title": (test_result or {}).get("testTitle", ""),
                "Current Performance": current_perf,
                "Area to be Improved": "Focus on the weaknesses detected in this attempt.",
                "Recommended Course": [
                    rec.get("lessonTitle")
                    or rec.get("lesson_title")
                    or rec.get("courseTitle")
                    or rec.get("course_title")
                    or ""
                    for rec in flat_recs
                ],
                "Progress Compared to Previous Test": progress_heading_text,
                "Domain Comparison": [],
            }

    if history_result:
        if not summary_json.get("Progress Compared to Previous Test"):
            summary_json["Progress Compared to Previous Test"] = progress_heading_text

        domain_lines = _domain_improvement_summaries(domain_performance, language_code=language_code)
        if domain_lines:
            summary_json["Domain Comparison"] = domain_lines

    if all_correct:
        summary_json["Recommended Course"] = []

    return summary_json


def _parse_llm_json(raw_text: str) -> Dict[str, Any]:
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        return {}
    return {}


# ---------------------------------------------------------------------------------------------
# Helper function - prep recommendation list
# ---------------------------------------------------------------------------------------------
def _flatten_recommendations(recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for entry in recommendations:
        recs = entry.get("recommendedCourses") or entry.get("recommended_courses") or []
        for rec in recs:
            flat.append(rec)
    return flat


def _summary_to_paragraph(summary_json: Dict[str, Any], recs: List[Dict[str, Any]]) -> str:
    lines: List[str] = []

    def add_line(label: str, value: str) -> None:
        if value:
            lines.append(f"**{label}:** {value}")

    title = summary_json.get("Test Title") or ""
    current = summary_json.get("Current Performance") or ""
    area = summary_json.get("Area to be Improved") or ""
    next_steps = summary_json.get("Next Steps to Explore") or ""
    progress = summary_json.get("Progress Compared to Previous Test") or ""

    if title:
        lines.append(f"**{title}**")
    add_line("Current Performance", current)
    if next_steps:
        add_line("Next Steps to Explore", next_steps)
    else:
        add_line("Area to be Improved", area)
    if progress:
        lines.append(f"**{progress}**")

    domain_comparison = summary_json.get("Domain Comparison") or []
    if isinstance(domain_comparison, list):
        domain_lines = [line.strip() for line in domain_comparison if isinstance(line, str) and line.strip()]
        if domain_lines:
            lines.append("**Domain Comparison:**")
            for line in domain_lines:
                if ":" in line:
                    name, rest = line.split(":", 1)
                    lines.append(f"- **{name.strip()}**:{rest}")
                else:
                    lines.append(f"- **{line}**")

    rec_notes = summary_json.get("Recommended Course") or []
    if not isinstance(rec_notes, list):
        rec_notes = []
    max_len = max(len(recs), len(rec_notes))

    course_lines: List[str] = []
    for idx in range(max_len):
        rec = recs[idx] if idx < len(recs) else {}
        note = rec_notes[idx] if idx < len(rec_notes) else ""
        title = (
            rec.get("lessonTitle")
            or rec.get("lesson_title")
            or rec.get("courseTitle")
            or rec.get("course_title")
            or ""
        )
        link = (
            rec.get("link")
            or rec.get("courseLink")
            or rec.get("course_link")
            or ""
        )

        parts: List[str] = []
        if title:
            parts.append(title)
        if note:
            note_text = note
            if title:
                note_text = note_text.replace(f"{title}:", "").replace(f"{title} -", "").strip()
            parts.append(f"{note_text}")
        if link:
            parts.append(f"Link: {link}")
        if parts:
            course_title = parts[0]
            rest = " - ".join(parts[1:]) if len(parts) > 1 else ""
            if rest:
                course_lines.append(f"**{course_title}**: {rest}")
            else:
                course_lines.append(f"**{course_title}**")

    if course_lines:
        lines.append("**Recommended Course:**")
        for line in course_lines:
            lines.append(f"- {line}")

    return "\n\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Helper function - participant ranking
# ---------------------------------------------------------------------------------------------
def _format_ranking(
    participant_ranking: float,
    *,
    language_code: str,
    mode: str,
) -> str:
    if participant_ranking <= 0:
        return "N/A" if mode == "prompt" else ""
    try:
        pct = participant_ranking * 100 if participant_ranking <= 1 else participant_ranking
    except (TypeError, ValueError):
        return "N/A" if mode == "prompt" else ""

    if mode == "prompt":
        return f"{participant_ranking} (approx. top {pct:.1f}% of participants)"
    if language_code == "TH":
        return f"อยู่ในกลุ่มบน {pct:.1f}% ของผู้เข้าสอบ."
    return f"Ranked within the top {pct:.1f}% of participants."


# ---------------------------------------------------------------------------------------------
# Helper function - progress comparison header
# ---------------------------------------------------------------------------------------------
def _progress_heading(
    test_result: Optional[Dict[str, Any]],
    history_result: Optional[Dict[str, Any]],
) -> str:
    if not history_result:
        return ""
    title = (test_result or {}).get("testTitle") or (history_result or {}).get("testTitle")
    if title:
        return f"Progress Compared to Previous Test ({title})"
    return "Progress Compared to Previous Test"


def _domain_improvement_summaries(
    domain_performance: Optional[Dict[str, Any]],
    *,
    language_code: str,
) -> List[str]:
    if not domain_performance:
        return []

    current = (domain_performance or {}).get("current") or {}
    history = (domain_performance or {}).get("history") or {}

    curr_domains = {d["domain"]: d for d in (current.get("domains") or []) if "domain" in d}
    hist_domains = {d["domain"]: d for d in (history.get("domains") or []) if "domain" in d}

    summaries: List[str] = []
    for domain, curr in curr_domains.items():
        if domain not in hist_domains:
            continue
        hist = hist_domains[domain]
        curr_acc = curr.get("accuracy")
        hist_acc = hist.get("accuracy")
        if curr_acc is None or hist_acc is None:
            continue

        delta = (curr_acc - hist_acc) * 100
        curr_pct = curr_acc * 100
        hist_pct = hist_acc * 100

        if language_code == "TH":
            if abs(delta) < 0.5:
                summaries.append(
                    f"{domain}: รักษาความแม่นยำ {curr_pct:.0f}% แสดงถึงความเข้าใจที่สม่ำเสมอในเนื้อหานี้."
                )
                continue
            direction = "ดีขึ้น" if delta > 0 else "ลดลง"
            summaries.append(
                f"{domain}: {direction} {delta:+.0f}% (จาก {hist_pct:.0f}% เป็น {curr_pct:.0f}%)."
            )
            continue

        if abs(delta) < 0.5:
            summaries.append(
                f"{domain}: Maintained {curr_pct:.0f}% accuracy, demonstrating consistent mastery of the subject."
            )
            continue

        direction = "Improved" if delta > 0 else "Declined"
        summaries.append(
            f"{domain}: {direction} by {delta:+.0f}% (from {hist_pct:.0f}% to {curr_pct:.0f}% accuracy)."
        )
    return summaries
