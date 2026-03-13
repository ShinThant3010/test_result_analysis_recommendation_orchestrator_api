# Test Result Analysis Recommendation Orchestrator API

FastAPI orchestrator that calls:
- test_analysis_api
- course_recommendation_api

## Endpoints
- `GET /health`
- `POST /v1/orchestrator/test-result-analysis-and-recommendations`

Example request (camelCase):
```json
{
  "studentId": "STUDENT_A",
  "testId": "TEST_CS_101",
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
  "participantRanking": 0.317,
  "language": "EN"
}
```

Optional request fields:
- `participantRanking`: optional fractional ranking (default: 0).

Example response (plain text, Markdown):
```json
"**Computer Science 101**\n\n**Current Performance:** ..."
```

## Environment Variables
Default values are loaded from `modules/parameters/config.yaml`. Any matching environment variable overrides YAML.

- `TEST_ANALYSIS_API_BASE_URL`
- `COURSE_RECOMMENDATION_API_BASE_URL`
- `GOOGLE_API_KEY`
- `GENERATION_MODEL` (default: `gemini-2.5-flash`)
- `DEFAULT_MAX_COURSES_PER_WEAKNESS` (default: `3`)
- `API_BEARER_TOKEN` (optional)
- `RESPONSE_LOG_PATH` (optional, default: `log/response_log.json`)
- `USER_FACING_RESPONSE_LOG_PATH` (optional, default: `log/user_facing_response_log.md`)

## Run Locally
```bash
uvicorn api.app:app --host 0.0.0.0 --port 8080
```


## Logging
- `log/response_log.json` contains per-run JSON logs (appends, keeps last 50).
- `log/user_facing_response_log.md` contains per-run markdown responses (appends).
- `log/response_log.json` contains upstream API responses (appends, keeps last 50).
