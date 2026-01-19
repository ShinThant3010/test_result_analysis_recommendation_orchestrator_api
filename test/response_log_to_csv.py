import argparse
import csv
import json
import os
import sys


def _find_entry(entries, name, entry_type=None):
    for entry in entries:
        if entry.get("name") != name:
            continue
        if entry_type and entry.get("type") != entry_type:
            continue
        return entry
    return {}


def _max_runtime(entries, predicate):
    runtimes = [entry.get("runtime", 0) for entry in entries if predicate(entry)]
    return max(runtimes) if runtimes else 0


def _rerank_stats(api_runtime):
    rerank_entries = [entry for entry in api_runtime if "rerank" in str(entry.get("usage", "")).lower()]
    if not rerank_entries:
        return 0, 0, 0, 0, 0
    input_tokens = sum(entry.get("input_token", 0) for entry in rerank_entries)
    output_tokens = sum(entry.get("output_token", 0) for entry in rerank_entries)
    count = len(rerank_entries)
    return input_tokens, output_tokens, input_tokens / count, output_tokens / count, count


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert response_log.json to CSV.")
    parser.add_argument(
        "--input",
        default="log/response_log.json",
        help="Path to response_log.json.",
    )
    parser.add_argument(
        "--output",
        default="log/response_log_csv.csv",
        help="Path to output CSV.",
    )
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1

    with open(args.input, encoding="utf-8") as file:
        payload = json.load(file)

    if not isinstance(payload, list):
        print("response_log.json must be a list of entries.", file=sys.stderr)
        return 1

    headers = [
        "test_case_no",
        "student_id",
        "test_id",
        "max_courses",
        "max_courses_per_weakness",
        "participant_ranking",
        "language",
        "orchestrator_runtime",
        "data_gathering_attempts",
        "data_gathering_questions",
        "test_analysis",
        "extract_weaknesses",
        "course_recommendation",
        "longest_vector_search",
        "longest_rerank",
        "user_facing_response",
        "response_input_token",
        "response_output_token",
        "test_analysis_input_token",
        "test_analysis_output_token",
        "rerank_input_token_total",
        "rerank_output_token_total",
        "rerank_input_token_avg",
        "rerank_output_token_avg",
        "num_weaknesses",
        "num_incorrect_answers",
    ]

    rows = []
    for idx, item in enumerate(payload, start=1):
        entries = item.get("entries", []) if isinstance(item.get("entries"), list) else []
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}

        attempts_entry = _find_entry(entries, "data_gathering_attempts", entry_type="api")
        questions_entry = _find_entry(entries, "data_gathering_questions", entry_type="api")
        test_analysis_entry = _find_entry(entries, "test_analysis", entry_type="api")
        course_rec_entry = _find_entry(entries, "course_recommendation", entry_type="api")
        user_facing_entry = _find_entry(entries, "user_facing_response", entry_type="llm")

        test_analysis_runtime = test_analysis_entry.get("request_runtime", 0)
        course_rec_runtime = course_rec_entry.get("request_runtime", 0)
        api_runtime = course_rec_entry.get("api_runtime", []) if isinstance(course_rec_entry.get("api_runtime"), list) else []

        extract_weaknesses_runtime = 0
        for runtime_entry in test_analysis_entry.get("api_runtime", []) if isinstance(test_analysis_entry.get("api_runtime"), list) else []:
            if str(runtime_entry.get("usage", "")).lower().startswith("extract_weaknesses"):
                extract_weaknesses_runtime = runtime_entry.get("runtime", 0)
                break

        longest_vector_search = _max_runtime(
            api_runtime, lambda entry: str(entry.get("usage", "")).lower().startswith("vector_search")
        )
        longest_rerank = _max_runtime(
            api_runtime, lambda entry: "rerank" in str(entry.get("usage", "")).lower()
        )

        (
            rerank_input_total,
            rerank_output_total,
            rerank_input_avg,
            rerank_output_avg,
            rerank_count,
        ) = _rerank_stats(api_runtime)

        weaknesses = (
            item.get("api_output", {})
            .get("test_analysis", {})
            .get("weaknesses", [])
        )
        num_weaknesses = len(weaknesses) if isinstance(weaknesses, list) else 0
        num_incorrect_answers = 0
        if isinstance(weaknesses, list):
            for weakness in weaknesses:
                if not isinstance(weakness, dict):
                    continue
                try:
                    num_incorrect_answers += int(weakness.get("frequency", 0))
                except (TypeError, ValueError):
                    continue

        rows.append(
            {
                "test_case_no": idx,
                "student_id": metadata.get("student_id", ""),
                "test_id": metadata.get("test_id", ""),
                "max_courses": metadata.get("max_courses", ""),
                "max_courses_per_weakness": metadata.get("max_courses_per_weakness", ""),
                "participant_ranking": metadata.get("participant_ranking", ""),
                "language": metadata.get("language", ""),
                "orchestrator_runtime": item.get("orchestrator_runtime", 0),
                "data_gathering_attempts": attempts_entry.get("request_runtime", 0),
                "data_gathering_questions": questions_entry.get("request_runtime", 0),
                "test_analysis": test_analysis_runtime,
                "extract_weaknesses": extract_weaknesses_runtime,
                "course_recommendation": course_rec_runtime,
                "longest_vector_search": longest_vector_search,
                "longest_rerank": longest_rerank,
                "user_facing_response": user_facing_entry.get("llm_runtime", 0),
                "response_input_token": user_facing_entry.get("input_token", 0),
                "response_output_token": user_facing_entry.get("output_token", 0),
                "test_analysis_input_token": test_analysis_entry.get("input_token", 0),
                "test_analysis_output_token": test_analysis_entry.get("output_token", 0),
                "rerank_input_token_total": rerank_input_total,
                "rerank_output_token_total": rerank_output_total,
                "rerank_input_token_avg": rerank_input_avg,
                "rerank_output_token_avg": rerank_output_avg,
                "num_weaknesses": num_weaknesses,
                "num_incorrect_answers": num_incorrect_answers,
            }
        )

    with open(args.output, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
