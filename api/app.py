from __future__ import annotations

import os
import time
import threading
import uuid

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from api.schema import OrchestrateRequest, PreviousAttemptDomainStat
from modules.core.orchestrator import OrchestrateInput, OrchestratorService


load_dotenv()

app = FastAPI(
    title="Test Analysis & Courses Recommendation Orchestrator API",
    version="0.1.0",
    description="Orchestrates test analysis and course recommendation APIs from caller-provided payload data.",
)

service = OrchestratorService()

_active_correlation_ids: set[str] = set()
_corr_lock = threading.Lock()
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN")

CORRELATION_HEADER = "X-Correlation-Id"
API_VERSION_HEADER = "X-API-Version"
SUPPORTED_API_VERSIONS = {"1"}
# ---------------------------------------------------------------------------------------------
# exception handlers
# ---------------------------------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    correlation_id = (
        (exc.headers or {}).get(CORRELATION_HEADER)
        or request.headers.get(CORRELATION_HEADER)
        or f"corr_{uuid.uuid4()}"
    )
    api_version = (
        (exc.headers or {}).get(API_VERSION_HEADER)
        or request.headers.get(API_VERSION_HEADER)
        or "1"
    )
    headers = {CORRELATION_HEADER: correlation_id, API_VERSION_HEADER: api_version}
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = request.headers.get(CORRELATION_HEADER) or f"corr_{uuid.uuid4()}"
    api_version = request.headers.get(API_VERSION_HEADER) or "1"
    headers = {CORRELATION_HEADER: correlation_id, API_VERSION_HEADER: api_version}
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"}, headers=headers)


# ---------------------------------------------------------------------------------------------
# API Header
# ---------------------------------------------------------------------------------------------
def _validate_request_headers(
    *,
    correlation_id: str,
    version: str,
    content_type: str | None,
    authorization: str | None,
) -> None:
    
    ### ----------------------------- validate version ----------------------------- ###
    if version not in SUPPORTED_API_VERSIONS:
        detail = {
            "code": "INVALID_FIELD_VALUE",
            "message": f"Unsupported X-API-Version: {version}",
            "correlationId": correlation_id,
        }
        raise HTTPException(
            status_code=400,
            detail=detail,
            headers={CORRELATION_HEADER: correlation_id, API_VERSION_HEADER: version},
        )

    ### --------------------------- validate content_type --------------------------- ###
    if content_type and not content_type.lower().startswith("application/json"):
        detail = {
            "code": "INVALID_CONTENT_TYPE",
            "message": f"Content-Type must be application/json, got: {content_type}",
            "correlationId": correlation_id,
        }
        raise HTTPException(
            status_code=415,
            detail=detail,
            headers={CORRELATION_HEADER: correlation_id, API_VERSION_HEADER: version},
        )

    ### --------------------------- validate authentication --------------------------- ###
    if API_BEARER_TOKEN:
        expected = f"Bearer {API_BEARER_TOKEN}"
        if authorization != expected:
            detail = {
                "code": "UNAUTHORIZED",
                "message": "Invalid or missing Authorization header.",
                "correlationId": correlation_id,
            }
            raise HTTPException(
                status_code=401,
                detail=detail,
                headers={CORRELATION_HEADER: correlation_id, API_VERSION_HEADER: version},
            )


def require_headers(
    response: Response,
    x_api_version: str | None = Header(None, alias=API_VERSION_HEADER, include_in_schema=False),
    x_correlation_id: str | None = Header(None, alias=CORRELATION_HEADER, include_in_schema=False),
    content_type: str | None = Header(None, alias="Content-Type", include_in_schema=False),
    authorization: str | None = Header(None, alias="Authorization", include_in_schema=False),
) -> dict[str, str]:
    
    correlation_id = x_correlation_id or f"corr_{uuid.uuid4()}"
    response.headers[CORRELATION_HEADER] = correlation_id
    version = (x_api_version or "1").strip() or "1"
    response.headers[API_VERSION_HEADER] = version

    _validate_request_headers(
        correlation_id=correlation_id,
        version=version,
        content_type=content_type,
        authorization=authorization,
    )

    return {"correlation_id": correlation_id, "api_version": version}

@app.middleware("http")
async def response_time_header(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    response.headers["X-Response-Time-Seconds"] = f"{elapsed:.4f}"
    return response

@app.on_event("shutdown")
async def shutdown_event() -> None:
    await service.close()


# ---------------------------------------------------------------------------------------------
# Endpoint 1: Health Check
# ---------------------------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "test_result_analysis_recommendation_orchestrator_api",
        "environment": "prod",
    }


# ---------------------------------------------------------------------------------------------
# Endpoint 2: Core API Endpoint - Test Result Analysis & Recommendations
# ---------------------------------------------------------------------------------------------
@app.post(
    "/v1/orchestrator/test-result-analysis-and-recommendations",
    summary="Execute test analysis and course recommendation orchestrator (v1)",
)
async def orchestrate(
    payload: OrchestrateRequest,
    response: Response,
    context: dict[str, str] = Depends(require_headers),
) -> Response:
    correlation_id = context["correlation_id"]

    ### ----------------- correction id control for concurrent requests ----------------- ###
    with _corr_lock:
        if correlation_id in _active_correlation_ids:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "CONFLICT",
                    "message": "Request with this correlation id is already processing.",
                    "correlationId": correlation_id,
                },
                headers={CORRELATION_HEADER: correlation_id, API_VERSION_HEADER: context["api_version"]},
            )
        _active_correlation_ids.add(correlation_id)

    ### --------- core function call for test result analysis & recommendations --------- ###
    try:
        orchestrate_input = OrchestrateInput(
            student_id=payload.student_id,
            test_id=payload.test_id,
            test_title=payload.test_title,
            max_courses=payload.max_courses,
            max_courses_per_weakness=payload.max_courses_per_weakness,
            participant_ranking=payload.participant_ranking,
            language=payload.language,
            current_attempt=payload.current_attempt.model_dump(by_alias=False),
            previous_attempt=(
                None
                if payload.previous_attempt is None
                else {
                    "domains": [
                        item.model_dump(by_alias=False)
                        if isinstance(item, PreviousAttemptDomainStat)
                        else item
                        for item in payload.previous_attempt
                    ]
                }
                if isinstance(payload.previous_attempt, list)
                else payload.previous_attempt.model_dump(by_alias=False)
            ),
        )
        orchestrator_result = await service.orchestrate(orchestrate_input)

    ### --------------------------------- Error Control --------------------------------- ###
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": str(exc),
                "correlationId": correlation_id,
            },
            headers={CORRELATION_HEADER: correlation_id, API_VERSION_HEADER: context["api_version"]},
        )

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "UPSTREAM_UNAVAILABLE",
                "message": f"Upstream error: {exc}",
                "correlationId": correlation_id,
            },
            headers={CORRELATION_HEADER: correlation_id, API_VERSION_HEADER: context["api_version"]},
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": f"Orchestrator failed: {exc}",
                "correlationId": correlation_id,
            },
            headers={CORRELATION_HEADER: correlation_id, API_VERSION_HEADER: context["api_version"]},
        )

    finally:
        with _corr_lock:
            _active_correlation_ids.discard(correlation_id)

    ### ------------------------------------ Reponse ------------------------------------ ###
    response.status_code = 200
    response_headers = {
        CORRELATION_HEADER: correlation_id,
        API_VERSION_HEADER: context["api_version"],
    }
    return Response(
        content=orchestrator_result["user_facing_paragraph"],
        media_type="text/markdown",
        headers=response_headers,
    )
