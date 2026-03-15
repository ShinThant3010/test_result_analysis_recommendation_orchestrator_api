from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from modules.utils.load_config import SETTINGS
from modules.utils.llm import generate_content_with_logging
from modules.utils.load_prompt import render_prompt

DEFAULT_LANGUAGE = SETTINGS.defaults.language
GENERATION_MODEL = SETTINGS.service.generation_model


@dataclass
class ResponseContext:
    language_code: str
    all_correct: bool
    test_result: Dict[str, Any]
    history_result: Optional[Dict[str, Any]]
    incorrect_summary: Dict[str, Any]
    domain_performance: Optional[Dict[str, Any]]
    weaknesses_text: str
    recommended_courses: List[Dict[str, Any]]
    ranking_sentence_text: str
    ranking_prompt_text: str
    progress_heading_text: str


# ---------------------------------------------------------------------------------------------
# Helper function - build exam result payload for response context
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
# Core function - generate user-facing response based on exam results, weaknesses, recommendations, and history
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
    """Generates a user-facing response summarizing 
       the test results, weaknesses, recommendations, and progress compared to history."""
    
    # Step 1: Build the response context with all necessary information
    context = _build_response_context(
        weaknesses=weaknesses,
        recommendations=recommendations,
        test_result=test_result,
        history_result=history_result,
        incorrect_summary=incorrect_summary,
        all_correct=all_correct,
        participant_ranking=participant_ranking,
        domain_performance=domain_performance,
        language=language,
    )

    # Step 2: Build the prompt for summary generation using the context
    prompt = _build_summary_prompt(context)

    # Step 3: Generate the summary JSON using the LLM and finalize it with any necessary enrichments
    summary_json = _generate_summary_json(prompt)

    # Step 4: Finalize the summary JSON by filling in any missing fields with fallback logic and enriching it with additional insights
    summary_json = _finalize_summary(summary_json=summary_json, context=context)

    # Step 5: Convert the finalized summary JSON into a user-friendly paragraph format for display
    paragraph = _summary_to_paragraph(summary_json, context.recommended_courses)
    return paragraph


def _build_response_context(
    *,
    weaknesses: List[Dict[str, Any]],
    recommendations: List[Dict[str, Any]],
    test_result: Optional[Dict[str, Any]],
    history_result: Optional[Dict[str, Any]],
    incorrect_summary: Dict[str, Any],
    all_correct: bool,
    participant_ranking: float,
    domain_performance: Optional[Dict[str, Any]],
    language: str,
) -> ResponseContext:
    """Builds the response context by processing the input data and preparing it for prompt generation."""

    language_code = (language or DEFAULT_LANGUAGE).strip().upper()

    # Flatten the list of recommendations and extract the relevant course information.
    recommended_courses = _extract_recommended_courses(recommendations)
    if all_correct:
        recommended_courses = []

    # Prepare a text block summarizing the weaknesses for inclusion in the prompt, 
    # ensuring to capture the most relevant information (weakness name, description, or any available text).
    weaknesses_text = "\n".join(
        f"- {w.get('weakness') or w.get('text') or w.get('description') or ''}"
        for w in weaknesses
    )

    return ResponseContext(
        language_code=language_code,
        all_correct=all_correct,
        test_result=test_result or {},
        history_result=history_result,
        incorrect_summary=incorrect_summary or {},
        domain_performance=domain_performance,
        weaknesses_text=weaknesses_text,
        recommended_courses=recommended_courses,
        ranking_sentence_text=_format_ranking(
            participant_ranking,
            language_code=language_code,
            mode="sentence",
        ),
        ranking_prompt_text=_format_ranking(
            participant_ranking,
            language_code=language_code,
            mode="prompt",
        ),
        progress_heading_text=_progress_heading(test_result, history_result),
    )


def _build_summary_prompt(context: ResponseContext) -> str:
    """Builds the prompt for summary generation by rendering a template with the response context data."""

    # Prepare a text block summarizing the recommended courses for inclusion in the prompt
    recs_text = "\n".join(
        f"- {rec.get('lessonTitle') or rec.get('lesson_title') or rec.get('courseTitle') or rec.get('course_title') or ''}"
        for rec in context.recommended_courses
    )
    return render_prompt(
        "generate_user_facing_response",
        {
            "test_result_json": json.dumps(context.test_result, ensure_ascii=False, indent=2),
            "history_result_json": json.dumps(context.history_result or {}, ensure_ascii=False, indent=2),
            "incorrect_summary_json": json.dumps(context.incorrect_summary, ensure_ascii=False, indent=2),
            "ranking_text": context.ranking_prompt_text,
            "progress_heading_prompt": context.progress_heading_text or "N/A",
            "domain_performance_json": json.dumps(context.domain_performance or {}, ensure_ascii=False, indent=2),
            "all_correct": context.all_correct,
            "weaknesses_text": context.weaknesses_text,
            "recs_text": recs_text or "N/A",
            "language_code": context.language_code,
        },
    )


def _generate_summary_json(prompt: str) -> Dict[str, Any]:
    """Generates the summary JSON by sending the prompt to the LLM and parsing the output."""

    raw_text = generate_content_with_logging(
        model=GENERATION_MODEL,
        prompt=prompt,
        log_name="user_facing_response",
    )
    return _parse_llm_json(raw_text)


def _finalize_summary(
    *,
    summary_json: Dict[str, Any],
    context: ResponseContext,
) -> Dict[str, Any]:
    """Finalizes the summary JSON 
        by filling in any missing fields with fallback logic and 
        enriching it with additional insights based on the response context."""
    
    summary = summary_json or _build_fallback_summary(context)
    return _enrich_summary(summary_json=summary, context=context)


def _build_fallback_summary(context: ResponseContext) -> Dict[str, Any]:
    """Builds a fallback summary JSON in case the LLM output is incomplete or missing."""
    
    # If the user got everything correct, provide a positive performance summary and suggest next steps for further learning.
    if context.all_correct:
        if context.language_code == "TH":
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
        if context.ranking_sentence_text:
            current_perf = f"{current_perf} {context.ranking_sentence_text}"
        return {
            "Test Title": context.test_result.get("testTitle", ""),
            "Current Performance": current_perf,
            "Area to be Improved": "",
            "Next Steps to Explore": next_steps,
            "Recommended Course": [],
            "Progress Compared to Previous Test": context.progress_heading_text,
            "Domain Comparison": [],
        }

    current_perf = (
        "We reviewed your performance and identified areas to improve. "
        "Focus on practicing the weakest topics and reviewing core concepts to build accuracy."
    )
    # If participant ranking information is available, include it in the performance summary 
    if context.ranking_sentence_text:
        current_perf = f"{current_perf} {context.ranking_sentence_text}"

    # If the user has some incorrect answers, provide a constructive performance summary and suggest focusing on weaknesses for improvement.
    return {
        "Test Title": context.test_result.get("testTitle", ""),
        "Current Performance": current_perf,
        "Area to be Improved": "Focus on the weaknesses detected in this attempt.",
        "Recommended Course": [
            rec.get("lessonTitle")
            or rec.get("lesson_title")
            or rec.get("courseTitle")
            or rec.get("course_title")
            or ""
            for rec in context.recommended_courses
        ],
        "Progress Compared to Previous Test": context.progress_heading_text,
        "Domain Comparison": [],
    }


def _enrich_summary(
    *,
    summary_json: Dict[str, Any],
    context: ResponseContext,
) -> Dict[str, Any]:
    """Enriches the summary JSON with additional insights based on the response context, 
        such as progress comparison and domain performance summaries."""
    
    if context.history_result:
        if not summary_json.get("Progress Compared to Previous Test"):
            summary_json["Progress Compared to Previous Test"] = context.progress_heading_text

        domain_lines = _domain_improvement_summaries(
            context.domain_performance,
            language_code=context.language_code,
        )
        if domain_lines:
            summary_json["Domain Comparison"] = domain_lines

    if context.all_correct:
        summary_json["Recommended Course"] = []

    return summary_json


# ---------------------------------------------------------------------------------------------
# Helper function - parse llm output into json (if possible)
# ---------------------------------------------------------------------------------------------
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
def _extract_recommended_courses(recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
    """Formats the participant ranking into a user-friendly string."""

    # For participant_ranking, we expect a float between 0 and 1 representing the percentile (e.g., 0.05 for top 5%).
    if participant_ranking <= 0:
        return "N/A" if mode == "prompt" else ""
    
    # If the value is greater than 1, we assume it's already a percentage (e.g., 5 for top 5%) and use it directly.
    try:
        pct = participant_ranking * 100 if participant_ranking <= 1 else participant_ranking
    except (TypeError, ValueError):
        return "N/A" if mode == "prompt" else ""

    # Format the string based on the mode and language

    if mode == "prompt":
        # For prompt mode, we want a concise format that can be easily included in the LLM prompt.
        return f"{participant_ranking} (approx. top {pct:.1f}% of participants)"
    
    # For sentence mode, we want a more natural language format that can be included in the final response.
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


# ---------------------------------------------------------------------------------------------
# Helper function - domain improvement summaries
# ---------------------------------------------------------------------------------------------
def _domain_improvement_summaries(
    domain_performance: Optional[Dict[str, Any]],
    *,
    language_code: str,
) -> List[str]:
    """Generates summaries of domain performance improvements or declines based on current and historical data."""
    
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
