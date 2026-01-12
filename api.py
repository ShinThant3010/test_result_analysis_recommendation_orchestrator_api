from __future__ import annotations

import os
import threading
import uuid

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Response

from functions.models import OrchestrateEnvelope, OrchestrateRequest, OrchestrateResponse
from functions.service import OrchestratorService

load_dotenv()

app = FastAPI(
    title="Test Result Analysis Recommendation Orchestrator API",
    version="0.1.0",
    description="Orchestrates data gathering, test analysis, and course recommendation APIs.",
)
router_v1 = APIRouter(prefix="/api/v1", tags=["v1"])

service = OrchestratorService()

_active_correlation_ids: set[str] = set()
_corr_lock = threading.Lock()
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN")

CORRELATION_HEADER = "X-Correlation-Id"
API_VERSION_HEADER = "X-API-Version"
SUPPORTED_API_VERSIONS = {"1"}


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


@router_v1.post(
    "v1/orchestrator/test-result-analyze-and-recommend",
    response_model=OrchestrateEnvelope,
    response_model_by_alias=True,
    summary="Execute orchestrator pipeline (v1)",
)
async def orchestrate(
    body: OrchestrateRequest,
    response: Response,
    context: dict[str, str] = Depends(require_headers),
) -> OrchestrateEnvelope:
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
    return OrchestrateEnvelope(
        correlation_id=correlation_id,
        data=OrchestrateResponse(**payload),
    )


app.include_router(router_v1)
