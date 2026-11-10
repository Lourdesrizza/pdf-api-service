"""HTTP routes for liveness and readiness."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.schemas.responses import ErrorResponse

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "api"}


@router.get("/ready", responses={503: {"model": ErrorResponse}})
async def ready(request: Request):
    timeout = request.app.state.settings.ready_check_timeout_seconds
    extractor_ok, documents_ok = await asyncio.gather(
        request.app.state.extractor.health(timeout),
        request.app.state.documents.health(timeout),
    )
    if extractor_ok and documents_ok:
        return {"status": "ready", "dependencies": {"extractor": "ok", "documents": "ok"}}
    return JSONResponse(
        status_code=503,
        content={
            "error": "not_ready",
            "detail": "Uno o más servicios requeridos no están disponibles.",
            "dependencies": {
                "extractor": "ok" if extractor_ok else "unavailable",
                "documents": "ok" if documents_ok else "unavailable",
            },
        },
    )
