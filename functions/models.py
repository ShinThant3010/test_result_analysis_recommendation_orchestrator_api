from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from functions.config import DEFAULT_LANGUAGE, DEFAULT_MAX_COURSES
from functions.utils.json_naming_converter import snake_to_camel


class OrchestrateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=snake_to_camel)
    student_id: str = Field(..., description="Student identifier.")
    test_id: str = Field(..., description="Test identifier.")
    max_courses: int = Field(
        DEFAULT_MAX_COURSES, ge=1, description="Maximum courses per weakness."
    )
    language: str = Field(
        DEFAULT_LANGUAGE, description="Output language for the final response (EN or TH)."
    )


class OrchestrateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=snake_to_camel)
    status: str
    student_id: str
    test_id: str
    incorrect_summary: Dict[str, Any]
    weaknesses: List[Dict[str, Any]]
    recommendations: List[Dict[str, Any]]
    user_facing_response: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None



class OrchestrateEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=snake_to_camel)

    correlation_id: str
    data: OrchestrateResponse
