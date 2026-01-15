from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from google import genai

from functions.config import DEFAULT_LANGUAGE, GENERATION_MODEL
from functions.utils.run_logging import extract_token_counts, log_llm_call


def _get_genai_client() -> genai.Client:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is missing")
    return genai.Client(api_key=api_key)


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
    """
    LLM-based user-facing response, adapted from agent5_user_facing_response.py.
    """
    language_code = (language or DEFAULT_LANGUAGE).strip().upper()

    ranking_sentence_text = _format_ranking(
        participant_ranking, language_code=language_code, mode="sentence"
    )
    progress_heading_text = _progress_heading(test_result, history_result)

    if all_correct:
        current_perf_parts = ["Congratulations on answering every question correctly!"]
        if ranking_sentence_text:
            current_perf_parts.append(ranking_sentence_text)
        summary = {
            "Test Title": (test_result or {}).get("testTitle", ""),
            "Current Performance": " ".join(current_perf_parts),
            "Area to be Improved": "",
            "Recommended Course": [],
            "Progress Compared to Previous Test": progress_heading_text,
            "Domain Comparison": [],
        }
        return _summary_to_paragraph(summary, [])

    weaknesses_text = "\n".join(
        f"- {w.get('weakness') or w.get('text') or w.get('description') or ''}"
        for w in weaknesses
    )

    flat_recs = _flatten_recommendations(recommendations)
    recs_text = "\n".join(
        f"- {rec.get('lessonTitle') or rec.get('lesson_title') or rec.get('courseTitle') or rec.get('course_title') or ''}"
        for rec in flat_recs
    )

    ranking_text = _format_ranking(
        participant_ranking, language_code=language_code, mode="prompt"
    )
    progress_heading_prompt = progress_heading_text or "N/A"

    prompt = f"""
        You are generating a concise JSON report for a student based on weaknesses and recommended courses.

        Full test result for the CURRENT attempt:
        {json.dumps(test_result or {}, ensure_ascii=False, indent=2)}

        Previous attempt (if any):
        {json.dumps(history_result or {}, ensure_ascii=False, indent=2)}

        Incorrect-question summary:
        {json.dumps(incorrect_summary or {}, ensure_ascii=False, indent=2)}

        Participant ranking (optional). The value is fractional (e.g., 0.317 means top 31.7%):
        {ranking_text}

        Heading to use before the progress comparison if history exists:
        {progress_heading_prompt}

        Domain performance by attempt (if history is present, compare current vs previous):
        {json.dumps(domain_performance or {}, ensure_ascii=False, indent=2)}

        Weaknesses identified:
        {weaknesses_text}

        Selected recommended courses (do NOT change this list):
        {recs_text}

        --- REQUIRED OUTPUT FORMAT (JSON ONLY) ---
        {{
            "Test Title": "<the current test title>",
            "Current Performance": "<short paragraph summarizing current ability>",
            "Area to be Improved": "<short paragraph describing key skills to focus on>",
            "Recommended Course": [
                "<Course A explanation>",
                "<Course B explanation>",
                "..."
            ],
            "Progress Compared to Previous Test": "<if history exists, else empty string>",
            "Domain Comparison": [
                "<Domain A: Improved by +X%>",
                "<Domain B: Declined by -Y%>"
            ]
        }}

        --- TONE & FORMAT ---
        - Use a supportive and encouraging tone.
        - Keep each section concise (2-4 sentences).
        - Base "Current Performance" on the provided test result and incorrect summary, and include 1-2 short recommendations for how to improve the key skills.
        - If participant ranking is provided (not N/A), include a short ranking statement using that value.
        - If there is a previous attempt, set "Progress Compared to Previous Test" to the heading provided above; otherwise set it to an empty string.
        - If domain performance includes both current and history, add a concise domain-wise comparison highlighting improvements or declines; otherwise omit or leave the array empty.
        - Respond in the requested language: {language_code} (EN or TH). Keep JSON keys in English.
        - LANGUAGE RULE: All value strings (not keys) must be written in {language_code}. If TH, use natural Thai phrasing; if EN, use English.
        - Return ONLY valid JSON (no code fences, no commentary).
        """

    client = _get_genai_client()
    start = time.time()
    response = client.models.generate_content(
        model=GENERATION_MODEL,
        contents=[{"parts": [{"text": prompt}]}],
    )
    raw_text = (response.text or "").strip()
    input_tokens, output_tokens = extract_token_counts(response)
    log_llm_call(
        name="user_facing_response",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        llm_runtime=time.time() - start,
    )
    summary_json = _parse_llm_json(raw_text)

    if not summary_json:
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

        domain_lines = _domain_improvement_summaries(domain_performance)
        if domain_lines:
            summary_json["Domain Comparison"] = domain_lines

    paragraph = _summary_to_paragraph(summary_json, flat_recs)
    return paragraph


def _parse_llm_json(raw_text: str) -> Dict[str, Any]:
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        return {}
    return {}


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
    progress = summary_json.get("Progress Compared to Previous Test") or ""

    if title:
        lines.append(f"**{title}**")
    add_line("Current Performance", current)
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
    domain_performance: Optional[Dict[str, Any]]
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
