from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class ServiceConfig:
    project_location: str
    test_analysis_api_base_url: str
    course_recommendation_api_base_url: str
    test_analysis_path: str
    course_recommendation_path: str
    http_timeout_seconds: float
    generation_model: str


@dataclass(frozen=True)
class DefaultsConfig:
    max_courses: int
    max_courses_per_weakness: int
    language: str


@dataclass(frozen=True)
class LoggingConfig:
    response_log_path: str
    user_facing_response_log_path: str


@dataclass(frozen=True)
class Settings:
    service: ServiceConfig
    defaults: DefaultsConfig
    logging: LoggingConfig


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    section = payload.get(key, {})
    return section if isinstance(section, dict) else {}


def load_settings(config_path: str = "modules/parameters/config.yaml") -> Settings:
    load_dotenv()
    cfg = _read_yaml(Path(config_path))

    service_cfg = _section(cfg, "service")
    defaults_cfg = _section(cfg, "defaults")
    logging_cfg = _section(cfg, "logging")

    project_location = str(
        os.getenv(
            "PROJECT_LOCATION",
            service_cfg.get("project_location", "810737581373.asia-southeast1"),
        )
    )

    return Settings(
        service=ServiceConfig(
            project_location=project_location,
            test_analysis_api_base_url=str(
                os.getenv(
                    "TEST_ANALYSIS_API_BASE_URL",
                    service_cfg.get(
                        "test_analysis_api_base_url",
                        f"https://test-analysis-api-{project_location}.run.app",
                    ),
                )
            ),
            course_recommendation_api_base_url=str(
                os.getenv(
                    "COURSE_RECOMMENDATION_API_BASE_URL",
                    service_cfg.get(
                        "course_recommendation_api_base_url",
                        f"https://course-recommendation-api-{project_location}.run.app",
                    ),
                )
            ),
            test_analysis_path=str(
                os.getenv(
                    "TEST_ANALYSIS_PATH",
                    service_cfg.get("test_analysis_path", "/v1/test-analysis"),
                )
            ),
            course_recommendation_path=str(
                os.getenv(
                    "COURSE_RECOMMENDATION_PATH",
                    service_cfg.get("course_recommendation_path", "/v1/course-recommendations"),
                )
            ),
            http_timeout_seconds=_to_float(
                os.getenv("HTTP_TIMEOUT_SECONDS", service_cfg.get("http_timeout_seconds")),
                60.0,
            ),
            generation_model=str(
                os.getenv(
                    "GENERATION_MODEL",
                    service_cfg.get("generation_model", "gemini-2.5-flash"),
                )
            ),
        ),
        defaults=DefaultsConfig(
            max_courses=_to_int(
                os.getenv("DEFAULT_MAX_COURSES", defaults_cfg.get("max_courses")),
                5,
            ),
            max_courses_per_weakness=_to_int(
                os.getenv(
                    "DEFAULT_MAX_COURSES_PER_WEAKNESS",
                    defaults_cfg.get("max_courses_per_weakness"),
                ),
                3,
            ),
            language=str(
                os.getenv(
                    "DEFAULT_LANGUAGE",
                    defaults_cfg.get("language", "EN"),
                )
            ),
        ),
        logging=LoggingConfig(
            response_log_path=str(
                os.getenv(
                    "RESPONSE_LOG_PATH",
                    logging_cfg.get("response_log_path", "log/response_log.json"),
                )
            ),
            user_facing_response_log_path=str(
                os.getenv(
                    "USER_FACING_RESPONSE_LOG_PATH",
                    logging_cfg.get("user_facing_response_log_path", "log/user_facing_response_log.md"),
                )
            ),
        ),
    )


SETTINGS = load_settings()

project_location = SETTINGS.service.project_location
TEST_ANALYSIS_API_BASE_URL = SETTINGS.service.test_analysis_api_base_url
COURSE_RECOMMENDATION_API_BASE_URL = SETTINGS.service.course_recommendation_api_base_url
TEST_ANALYSIS_PATH = SETTINGS.service.test_analysis_path
COURSE_RECOMMENDATION_PATH = SETTINGS.service.course_recommendation_path
HTTP_TIMEOUT_SECONDS = SETTINGS.service.http_timeout_seconds
GENERATION_MODEL = SETTINGS.service.generation_model

DEFAULT_MAX_COURSES = SETTINGS.defaults.max_courses
DEFAULT_MAX_COURSES_PER_WEAKNESS = SETTINGS.defaults.max_courses_per_weakness
DEFAULT_LANGUAGE = SETTINGS.defaults.language

RESPONSE_LOG_PATH = SETTINGS.logging.response_log_path
USER_FACING_RESPONSE_LOG_PATH = SETTINGS.logging.user_facing_response_log_path
