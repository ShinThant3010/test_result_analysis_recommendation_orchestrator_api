# Test Result Analysis Recommendation Orchestrator API

FastAPI orchestrator that calls:
- data-gathering-api
- test_analysis_api
- course_recommendation_api

## Endpoints
- `GET /health`
- `POST /api/v1/orchestrate`

Example request (camelCase):
```json
{
  "studentId": "STUDENT_A",
  "testId": "01KCXGG0SS0001H0Q1FW1K4S0G",
  "maxCourses": 5,
  "language": "EN"
}
```

Example response (camelCase envelope):
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

## Environment Variables
- `DATA_GATHERING_API_BASE_URL`
- `TEST_ANALYSIS_API_BASE_URL`
- `COURSE_RECOMMENDATION_API_BASE_URL`
- `GOOGLE_API_KEY`
- `GENERATION_MODEL` (default: `gemini-2.5-flash`)
- `API_BEARER_TOKEN` (optional)

## Run Locally
```bash
uvicorn api:app --host 0.0.0.0 --port 8080
```


## Logging
- `data/run_log.json` contains per-run timing and token usage logs.
