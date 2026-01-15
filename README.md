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
  "maxCoursesPerWeakness": 3,
  "participantRanking": 0,
  "language": "EN"
}
```

Optional request fields:
- `maxCoursesPerWeakness`: limit courses returned per weakness (default: 3).
- `participantRanking`: optional fractional ranking (default: 0).

Example response (plain text, Markdown):
```json
"**Computer Science 101**\n\n**Current Performance:** ..."
```

## Environment Variables
- `DATA_GATHERING_API_BASE_URL`
- `TEST_ANALYSIS_API_BASE_URL`
- `COURSE_RECOMMENDATION_API_BASE_URL`
- `GOOGLE_API_KEY`
- `GENERATION_MODEL` (default: `gemini-2.5-flash`)
- `API_BEARER_TOKEN` (optional)
- `RESPONSE_LOG_PATH` (optional, default: `log/response_log.json`)
- `USER_FACING_RESPONSE_LOG_PATH` (optional, default: `log/user_facing_response_log.md`)

## Run Locally
```bash
uvicorn api:app --host 0.0.0.0 --port 8080
```


## Logging
- `log/response_log.json` contains per-run JSON logs (appends, keeps last 50).
- `log/user_facing_response_log.md` contains per-run markdown responses (appends).
- `log/response_log.json` contains upstream API responses (appends, keeps last 50).
