# Test Result Analysis Recommendation Orchestrator API

FastAPI orchestrator that calls:
- data-gathering-api
- test_analysis_api
- course_recommendation_api

## Endpoints
- `GET /health`
- `POST /orchestrate`

Example request:
```json
{
  "student_id": "STUDENT_A",
  "test_id": "01KCXGG0SS0001H0Q1FW1K4S0G",
  "max_courses": 5,
  "language": "EN"
}
```

## Environment Variables
- `DATA_GATHERING_API_BASE_URL`
- `TEST_ANALYSIS_API_BASE_URL`
- `COURSE_RECOMMENDATION_API_BASE_URL`
- `GOOGLE_API_KEY`
- `GENERATION_MODEL` (default: `gemini-2.5-flash`)

## Run Locally
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
```
