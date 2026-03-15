# Test Result Analysis Recommendation Orchestrator API (REST API Spec)

Service: **test_result_analysis_recommendation_orchestrator_api**

**Purpose**  
Analyze a student’s test results, extract weaknesses via Gemini, recommend courses via Vertex AI Matching Engine, and return a concise user-facing paragraph; Orchestrate data gathering, analyze test, extract weakness, and recommend course(s) through internal APIs, then generate a user-facing summary.

**High-Level Flow**
1. Fetch current and previous attempts for student/test. [Data Gathering API]
2. Extract incorrect answers for the current attempt. [Orchestrator API]
3. If incorrect answers exist, call test analysis API to derive weaknesses. [Test Analysis API]
4. Call course recommendation API using weaknesses. [Course Recommendation API]
5. Generate a structured summary via LLM, apply deterministic fallback/enrichment, and return markdown text. [Orchestrator API]

---

## Base URLs

**Production (Cloud Run):**  
`https://test-result-analysis-recommendation-orchestrator-<project>.run.app`

**Staging (Cloud Run):**  
`https://test-result-analysis-recommendation-orchestrator-<env>.run.app`

**Local (Uvicorn/FastAPI):**  
`http://127.0.0.1:8080`

**Swagger/OpenAPI:**  
`https://test-result-orchestrator-api-810737581373.asia-southeast1.run.app/docs`

---

## Guideline Alignment Notes

* ✅ **Resource-based URL:** `/v1/orchestrator/test-result-analysis-and-recommendations`
* ✅ **HTTP methods:** `GET` for health, `POST` for synchronous orchestration
* ✅ **HTTP status codes:** 2xx success, 4xx validation/not-found, 5xx pipeline errors
* ✅ **Correlation ID:** `X-Correlation-Id` passthrough + auto-generation
* ✅ **API Version header:** `X-API-Version` (default `1`, anything else ⇒ 400)
* ✅ **JSON naming:** requests and responses use **camelCase**
* ✅ **Idempotency guard:** correlation-id guard rejects concurrent duplicates (409)

---

## Authentication & Authorization [TBD]

Bearer auth is optional. When `API_BEARER_TOKEN` is set, requests must include:  
`Authorization: Bearer <API_BEARER_TOKEN>`

---

## Required Headers

- `Content-Type: application/json` (otherwise 415)
- `X-API-Version: 1` (defaults to 1; other values → 400)
- `X-Correlation-Id` (optional; server generates `corr_<uuid>` if missing; always echoed)

---

## Endpoints Summary

- `GET /health`
- `POST /v1/orchestrator/test-result-analysis-and-recommendations`

---

## 1) Health Endpoint

### GET /health
**Response:** `200 OK`

```json
{
  "status": "ok",
  "service": "test_result_analysis_recommendation_orchestrator_api",
  "environment": "prod"
}
```

---

## 2) Run Orchestrator Pipeline

### POST /v1/orchestrator/test-result-analysis-and-recommendations

Runs the orchestrator pipeline. Correlation IDs in-flight are rejected with `409 CONFLICT`.

#### Request Schema (camelCase)

| Field       | Type   | Required | Notes |
| ----------- | ------ | -------: | ----- |
| examResultId   | string | ✅ | Exam result identifier. |
| studentId   | string | ✅ | Student identifier. |
| testId      | string | ✅ | Assessment/test identifier. |
| maxCourses  | int    | ❌ | Max courses overall (default 5, min 1). |
| participantRanking | float | ❌ | Optional fractional ranking (e.g., 0.317 => top 31.7%). Default `0`. |
| language    | string | ❌ | `EN` or `TH` for the final summary (default `EN`). |
| currentAttempt | object | ✅ | Current attempt with question-level details. |
| previousAttempt | array<object> or object | ❌ | Previous domain summary. Accepts either a direct array of domain aggregates or `{ "domains": [...] }`. |

**Example**
```json
{
  "studentId": "STUDENT_A",
  "testId": "01KCXGG0SS0001H0Q1FW1K4S0G",
  "testTitle": "Computer Science 101",
  "currentAttempt": {
    "earnedScore": 7,
    "totalScore": 10,
    "status": "COMPLETED",
    "questions": [
      {
        "testResultQuestionId": "TRQ_001",
        "questionId": "Q_001",
        "questionText": "What is the time complexity of binary search?",
        "domain": "Algorithms",
        "explanation": "Binary search halves the search space each step.",
        "correctAnswers": [{ "answerId": "A_1", "value": "O(log n)" }],
        "selectedAnswers": [{ "answerId": "A_2", "value": "O(n)" }],
        "isCorrect": false
      }
    ]
  },
  "previousAttempt": [
    {
      "domain": "Algorithms",
      "correct_questions_count": 3,
      "incorrect_questions_count": 4
    }
  ],
  "maxCourses": 5,
  "participantRanking": 0,
  "language": "EN"
}
```

```
curl -i -X 'POST' \
  'https://test-result-orchestrator-api-810737581373.asia-southeast1.run.app/v1/orchestrator/test-result-analysis-and-recommendations' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "studentId": "STUDENT_A",
  "testId": "01KCXGG0SS0001H0Q1FW1K4S0G",
  "testTitle": "Computer Science 101",
  "currentAttempt": {
    "earnedScore": 7,
    "totalScore": 10,
    "status": "COMPLETED",
    "questions": [
      {
        "testResultQuestionId": "TRQ_001",
        "questionId": "Q_001",
        "questionText": "What is the time complexity of binary search?",
        "domain": "Algorithms",
        "explanation": "Binary search halves the search space each step.",
        "correctAnswers": [{ "answerId": "A_1", "value": "O(log n)" }],
        "selectedAnswers": [{ "answerId": "A_2", "value": "O(n)" }],
        "isCorrect": false
      }
    ]
  },
  "previousAttempt": [
    {
      "domain": "Algorithms",
      "correct_questions_count": 3,
      "incorrect_questions_count": 4
    }
  ],
  "maxCourses": 5,
  "participantRanking": 0,
  "language": "EN"
}'
```

#### Responses
Headers always echo `X-Correlation-Id`, `X-API-Version` and `x-response-time-seconds`.

**200 OK — success**
```
text
HTTP/2 200 
x-correlation-id: corr_f5a5e236-f0fa-4390-be9e-1667c9d5faa1
x-api-version: 1
content-type: text/markdown; charset=utf-8
x-response-time-seconds: 23.0280
x-cloud-trace-context: d90a57f613c5caaad5a777bd06230613;o=1
date: Wed, 04 Feb 2026 04:03:49 GMT
server: Google Frontend
content-length: 2102
alt-svc: h3=":443"; ma=2592000,h3-29=":443"; ma=2592000

**Computer Science 101**

**Current Performance:** You achieved an excellent score of 19 out of 20 (95%) on the Computer Science 101 test, successfully passing. Your strong performance demonstrates a solid grasp of the subject matter, with only one question answered incorrectly. This indicates a high level of understanding across most areas of the test.

**Area to be Improved:** Your primary area for refinement is Python String Slicing, specifically understanding the exclusive nature of the stop index. Mastering this concept will ensure precise manipulation of strings and eliminate subtle errors in your Python code. Consistent practice with various slicing scenarios will help solidify this skill.

**Progress Compared to Previous Test (Computer Science 101)**

**Domain Comparison:**

- **Python**: Maintained 80% accuracy, demonstrating consistent mastery of the subject.

- **Algebra**: Improved by +20% (from 80% to 100% accuracy).

- **Database**: Improved by +60% (from 40% to 100% accuracy).

- **Data Visualization**: Maintained 100% accuracy, demonstrating consistent mastery of the subject.

**Recommended Course:**

- **Programming for Everybody (Getting Started with Python)**: This course is ideal for strengthening your foundational Python concepts, which is crucial for mastering areas like string manipulation and ensuring robust programming skills. - Link: https://www.edx.org/course/programming-for-everybody-getting-started-with-pyt

- **Computing in Python I: Fundamentals and Procedural Programming**: This course will deepen your understanding of Python fundamentals and procedural programming, providing a comprehensive review that can help clarify intricate topics such as string slicing. - Link: https://www.edx.org/course/computing-in-python-i-fundamentals-and-procedural

- **Python Basics for Data Science**: While focused on data science, this course revisits Python basics, offering a solid review of string operations and other core programming skills, reinforcing your overall Python proficiency. - Link: https://www.edx.org/course/python-basics-for-data-science
```

#### User-Facing Response Notes

The success response is returned as `text/markdown`, not JSON. The response generator follows this pipeline:

1. Normalize test result, weakness, recommendation, ranking, and historical data.
2. Render the `generate_user_facing_response` prompt template.
3. Ask the configured generation model for a JSON summary.
4. Parse the model output and fall back to deterministic summary text if parsing fails or the payload is empty.
5. Enrich the summary with:
   - a historical progress heading when previous results exist
   - domain-level improvement/decline lines when current and historical domain accuracy are both available
   - removal of recommended courses when the learner answered every question correctly
6. Render the final markdown paragraph/section output.

Typical markdown sections are:
- `Current Performance`
- `Area to be Improved` or `Next Steps to Explore`
- `Progress Compared to Previous Test (...)`
- `Domain Comparison`
- `Recommended Course`

**Other status codes**
- `401` unauthorized (when bearer token is configured)
- `404` missing student/test data
- `409` duplicate `X-Correlation-Id` already in-flight (`CONFLICT`)
- `415` invalid content type
- `502` upstream dependency unavailable (`UPSTREAM_UNAVAILABLE`)
- `500` unexpected pipeline failure (`INTERNAL_ERROR`)

---

## 3) Standard Error Format

Errors use camelCase keys:

```json
{
  "code": "INVALID_FIELD_VALUE",
  "message": "Unsupported X-API-Version: 2",
  "correlationId": "corr_abc123"
}
```

---

## 4) Internal Dependencies

| Component | Purpose | Notes |
| --------- | ------- | ----- |
| data-gathering-api | Fetch exam attempts + question bank | Uses configured Cloud Run URL in `modules/utils/load_config.py`. |
| test_analysis_api | Extracts weaknesses from incorrect answers | Uses configured Cloud Run URL in `modules/utils/load_config.py`. |
| course_recommendation_api | Recommends courses from weaknesses | Uses configured Cloud Run URL in `modules/utils/load_config.py`. |
| LLM response (service.py) | Generates user-facing summary | Uses Gemini model (`GENERATION_MODEL`). |

---

## 5) Change Log

* **2025-02-01**: Initial specification drafted.
