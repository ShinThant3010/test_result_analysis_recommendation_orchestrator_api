from __future__ import annotations

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from .models import OrchestrateRequest, OrchestrateResponse
from .service import OrchestratorService

load_dotenv()


app = FastAPI(
    title="Test Result Analysis Recommendation Orchestrator API",
    version="0.1.0",
)

service = OrchestratorService()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await service.close()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/orchestrate", response_model=OrchestrateResponse)
async def orchestrate(body: OrchestrateRequest) -> OrchestrateResponse:
    try:
        payload = await service.orchestrate(
            student_id=body.student_id,
            test_id=body.test_id,
            max_courses=body.max_courses,
            language=body.language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream error: {exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Orchestrator failed: {exc}")

    return OrchestrateResponse(**payload)
