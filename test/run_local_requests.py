import argparse
import csv
import json
import sys
import socket
import urllib.error
import urllib.request


def _post_json(url: str, payload: dict, timeout: float) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, body
    except socket.timeout:
        return 0, "timeout"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        return exc.code, body


def main() -> int:
    parser = argparse.ArgumentParser(description="Run orchestrator requests from a CSV file.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080",
        help="Base URL for the orchestrator service.",
    )
    parser.add_argument(
        "--csv",
        default="test/test_input.csv",
        help="CSV file containing exam_result_id, user_id and test_id columns.",
    )
    parser.add_argument("--language", default="EN", help="Output language (EN or TH).")
    parser.add_argument("--max-courses", type=int, default=5, help="Max courses overall.")
    parser.add_argument(
        "--max-courses-per-weakness",
        type=int,
        default=3,
        help="Max courses per weakness.",
    )
    parser.add_argument(
        "--participant-ranking",
        type=float,
        default=0.0,
        help="Participant ranking (fractional, e.g., 0.317).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only run the first N rows (0 = all).",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds.")
    args = parser.parse_args()

    endpoint = f"{args.base_url}/v1/orchestrator/test-result-analysis-and-recommendations"

    with open(args.csv, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    if not rows:
        print("No rows found in CSV.", file=sys.stderr)
        return 1

    limit = args.limit if args.limit and args.limit > 0 else len(rows)
    for idx, row in enumerate(rows[:limit], start=1):
        exam_result_id = (row.get("exam_result_id") or "").strip()
        user_id = (row.get("user_id") or "").strip()
        test_id = (row.get("test_id") or "").strip()
        if not exam_result_id or not user_id or not test_id:
            print(f"[{idx}] Skipping row with missing exam_result_id/user_id/test_id.")
            continue

        payload = {
            "examResultId": exam_result_id,
            "studentId": user_id,
            "testId": test_id,
            "maxCourses": args.max_courses,
            "maxCoursesPerWeakness": args.max_courses_per_weakness,
            "participantRanking": args.participant_ranking,
            "language": args.language,
        }

        status, body = _post_json(endpoint, payload, timeout=args.timeout)
        outcome = "ok" if 200 <= status < 300 else "error"
        preview = body.replace("\n", " ").strip()
        if len(preview) > 180:
            preview = f"{preview[:177]}..."
        print(f"[{idx}] {exam_result_id} {user_id} {test_id} -> {status} ({outcome}) {preview}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
