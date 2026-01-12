# Test Result Analysis Recommendation Orchestrator API (REST API Spec)

Service: **test_result_analysis_recommendation_orchestrator_api**

**Purpose**  
Orchestrate data gathering, test analysis, and course recommendation APIs, then generate a user-facing summary.

**High-Level Flow**
1. Fetch current and previous attempts for student/test.
2. Extract incorrect answers for the current attempt.
3. If incorrect answers exist, call test analysis API to derive weaknesses.
4. Call course recommendation API using weaknesses.
5. Generate a user-facing response via LLM.

---

## Base URLs

**Production (Cloud Run):**  
`https://test-result-analysis-recommendation-orchestrator-<project>.run.app`

**Staging (Cloud Run):**  
`https://test-result-analysis-recommendation-orchestrator-<env>.run.app`

**Local (Uvicorn/FastAPI):**  
`http://127.0.0.1:8080`

---

## Guideline Alignment Notes

* ✅ **Resource-based URL:** `/api/v1/orchestrate`
* ✅ **HTTP methods:** `GET` for health, `POST` for synchronous orchestration
* ✅ **HTTP status codes:** 2xx success, 4xx validation/not-found, 5xx pipeline errors
* ✅ **Correlation ID:** `X-Correlation-Id` passthrough + auto-generation
* ✅ **API Version header:** `X-API-Version` (default `1`, anything else ⇒ 400)
* ✅ **JSON naming:** requests and responses use **camelCase**
* ✅ **Idempotency guard:** correlation-id guard rejects concurrent duplicates (409)

---

## Authentication & Authorization

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
- `POST /api/v1/orchestrate`

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

### POST /api/v1/orchestrate

Runs the orchestrator pipeline. Correlation IDs in-flight are rejected with `409 CONFLICT`.

#### Request Schema (camelCase)

| Field       | Type   | Required | Notes |
| ----------- | ------ | -------: | ----- |
| studentId   | string | ✅ | Student identifier. |
| testId      | string | ✅ | Assessment/test identifier. |
| maxCourses  | int    | ❌ | Max courses per weakness (default 5, min 1). |
| language    | string | ❌ | `EN` or `TH` for the final summary (default `EN`). |

**Example**
```json
{
  "studentId": "STUDENT_A",
  "testId": "01KCXGG0SS0001H0Q1FW1K4S0G",
  "maxCourses": 5,
  "language": "EN"
}
```

#### Responses
Headers always echo `X-Correlation-Id` and `X-API-Version`.

**200 OK — success**
```json
{
  "correlationId": "corr_abc123",
  "data": {
    "status": "ok",
    "studentId": "STUDENT_A",
    "testId": "01KCXGG0SS0001H0Q1FW1K4S0G",
    "incorrectSummary": {
      "totalQuestionsInTest": 20,
      "totalIncorrectQuestions": 4
    },
    "weaknesses": ["..."],
    "recommendations": ["..."],
    "userFacingResponse": {
      "summary": {"...": "..."},
      "userFacingParagraph": "...",
      "recommendations": ["..."]
    }
  }
}
```

**200 OK — all correct (no analysis needed)**
```json
{
  "correlationId": "corr_abc123",
  "data": {
    "status": "all_correct",
    "studentId": "STUDENT_A",
    "testId": "01KCXGG0SS0001H0Q1FW1K4S0G",
    "incorrectSummary": {
      "totalQuestionsInTest": 20,
      "totalIncorrectQuestions": 0
    },
    "weaknesses": [],
    "recommendations": [],
    "userFacingResponse": {
      "summary": {"...": "..."},
      "userFacingParagraph": "...",
      "recommendations": []
    }
  }
}
```

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
| data-gathering-api | Fetch exam attempts + question bank | Uses configured Cloud Run URL in `functions/config.py`. |
| test_analysis_api | Extracts weaknesses from incorrect answers | Uses configured Cloud Run URL in `functions/config.py`. |
| course_recommendation_api | Recommends courses from weaknesses | Uses configured Cloud Run URL in `functions/config.py`. |
| LLM response (service.py) | Generates user-facing summary | Uses Gemini model (`GENERATION_MODEL`). |

---

## 5) Change Log

* **2025-02-01**: Initial specification drafted.
