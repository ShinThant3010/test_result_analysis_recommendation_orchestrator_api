from __future__ import annotations

import json
import os
import time
import threading
import uuid
import warnings
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic.warnings import UnsupportedFieldAttributeWarning

from functions.models import OrchestrateRequest
from functions.service import OrchestratorService
from functions.config import API_RESPONSE_LOG_PATH

warnings.filterwarnings("ignore", category=UnsupportedFieldAttributeWarning)

load_dotenv()

app = FastAPI(
    title="Test Analysis & Courses Recommendation Orchestrator API",
    version="0.1.0",
    description="Orchestrates data gathering, test analysis, and course recommendation APIs.",
)

service = OrchestratorService()

_active_correlation_ids: set[str] = set()
_corr_lock = threading.Lock()
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN")

CORRELATION_HEADER = "X-Correlation-Id"
API_VERSION_HEADER = "X-API-Version"
SUPPORTED_API_VERSIONS = {"1"}


def _write_api_response_log(
    *,
    api_status: int,
    api_headers: dict[str, str],
    body: object,
    metadata: dict[str, object] | None = None,
    run_id: str | None = None,
) -> None:
    log_payload = {
        "run_id": run_id or f"run_{uuid.uuid4().hex}",
        "api_status": api_status,
        "api_headers": api_headers,
        "body": body,
        "metadata": metadata or {},
    }
    path = Path(API_RESPONSE_LOG_PATH)
    existing: list[dict[str, object]]
    if path.exists():
        try:
            existing_data = json.loads(path.read_text())
            if isinstance(existing_data, list):
                existing = existing_data
            else:
                existing = []
        except Exception:  # noqa: BLE001
            existing = []
    else:
        existing = []
    existing.append(log_payload)
    path.write_text(json.dumps(existing, ensure_ascii=True, indent=2) + "\n")


def _request_metadata(request: Request, payload: object | None = None) -> dict[str, object]:
    return {
        "method": request.method,
        "url": str(request.url),
        "query_params": dict(request.query_params),
        "body": payload,
    }


async def _request_metadata_from_request(request: Request) -> dict[str, object]:
    payload: object | None = None
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        try:
            raw = await request.body()
            if raw:
                payload = raw.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            payload = None
    return _request_metadata(request, payload=payload)


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
    try:
        _write_api_response_log(
            api_status=exc.status_code,
            api_headers=headers,
            body={"detail": exc.detail},
            metadata={"request": await _request_metadata_from_request(request)},
        )
    except Exception as log_exc:  # noqa: BLE001
        warnings.warn(f"Failed to write API response log: {log_exc}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = request.headers.get(CORRELATION_HEADER) or f"corr_{uuid.uuid4()}"
    api_version = request.headers.get(API_VERSION_HEADER) or "1"
    headers = {CORRELATION_HEADER: correlation_id, API_VERSION_HEADER: api_version}
    try:
        _write_api_response_log(
            api_status=500,
            api_headers=headers,
            body={"detail": str(exc)},
            metadata={"request": await _request_metadata_from_request(request)},
        )
    except Exception as log_exc:  # noqa: BLE001
        warnings.warn(f"Failed to write API response log: {log_exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"}, headers=headers)


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


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "test_result_analysis_recommendation_orchestrator_api",
        "environment": "prod",
    }

@app.post(
    "/v1/orchestrator/test-result-analysis-and-recommendations",
    summary="Execute test analysis and course recommendation orchestrator (v1)",
)
async def orchestrate(
    body: OrchestrateRequest,
    request: Request,
    response: Response,
    context: dict[str, str] = Depends(require_headers),
) -> Response:
    correlation_id = context["correlation_id"]
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

    try:
        payload = await service.orchestrate(
            student_id=body.student_id,
            test_id=body.test_id,
            max_courses=body.max_courses,
            max_courses_per_weakness=body.max_courses_per_weakness,
            participant_ranking=body.participant_ranking,
            language=body.language,
        )

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
    
    except Exception as exc:  # noqa: BLE001
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

    response.status_code = 200
    response_headers = {
        CORRELATION_HEADER: correlation_id,
        API_VERSION_HEADER: context["api_version"],
    }
    try:
        _write_api_response_log(
            api_status=response.status_code,
            api_headers=response_headers,
            body=payload.get("user_facing_paragraph", ""),
            metadata={"request": _request_metadata(request, payload=body.model_dump())},
            run_id=payload.get("run_id"),
        )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"Failed to write API response log: {exc}")
    return Response(
        content=payload["user_facing_paragraph"],
        media_type="text/markdown",
        headers=response_headers,
    )
