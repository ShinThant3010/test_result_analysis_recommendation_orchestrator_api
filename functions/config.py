import os

project_location = "810737581373.asia-southeast1"

DATA_GATHERING_API_BASE_URL = os.getenv(
    "DATA_GATHERING_API_BASE_URL",
    "https://test-result-data-api-" + project_location + ".run.app",
)
TEST_ANALYSIS_API_BASE_URL = os.getenv(
    "TEST_ANALYSIS_API_BASE_URL",
    "https://test-analysis-api-" + project_location + ".run.app",
)
COURSE_RECOMMENDATION_API_BASE_URL = os.getenv(
    "COURSE_RECOMMENDATION_API_BASE_URL",
    "https://course-recommendation-api-" + project_location + ".run.app",
)

DATA_GATHERING_ATTEMPTS_PATH = "/v1/test-results/students/{student_id}/tests/{test_id}"
DATA_GATHERING_QUESTIONS_PATH = "/v1/tests/{test_id}/questions"
TEST_ANALYSIS_PATH = "/v1/test-analysis"
COURSE_RECOMMENDATION_PATH = "/v1/course-recommendations"

HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "30"))
DEFAULT_MAX_COURSES = int(os.getenv("DEFAULT_MAX_COURSES", "5"))
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "EN")
GENERATION_MODEL = os.getenv("GENERATION_MODEL", "gemini-2.5-flash")

RUN_LOG_PATH = os.getenv("RUN_LOG_PATH", "data/run_log.json")
