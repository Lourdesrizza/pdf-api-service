"""HTTP route for processing PDFs."""

from fastapi import APIRouter, Request

from app.auth import require_process_auth
from app.errors import APIError
from app.schemas.responses import ErrorResponse, ProcessResponse
from app.validation import receive_pdf

router = APIRouter()

PROCESS_OPENAPI_EXTRA = {
    "requestBody": {
        "required": True,
        "content": {
            "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            },
        },
    },
    "parameters": [
        {"name": name, "in": "header", "required": False, "schema": {"type": "string"}}
        for name in ("X-Filename", "X-Request-ID")
    ],
}
PROCESS_ERROR_RESPONSES = {
    status: {"model": ErrorResponse}
    for status in (400, 401, 408, 413, 415, 422, 500, 502, 503, 504)
}


@router.post(
    "/process",
    response_model=ProcessResponse,
    openapi_extra=PROCESS_OPENAPI_EXTRA,
    responses=PROCESS_ERROR_RESPONSES,
)
async def process(request: Request):
    settings = request.app.state.settings
    require_process_auth(request, settings)

    limit = settings.max_concurrent_requests
    if limit > 0:
        async with request.app.state.active_lock:
            if request.app.state.active_requests >= limit:
                raise APIError(
                    503,
                    "api_saturated",
                    "La API está ocupada; reintentá más tarde.",
                    {"Retry-After": "1"},
                )
            request.app.state.active_requests += 1

    try:
        pdf, filename = await receive_pdf(
            request, settings.max_upload_bytes, settings.body_timeout_seconds
        )
        return await request.app.state.orchestrator.process(pdf, filename)
    finally:
        if limit > 0:
            async with request.app.state.active_lock:
                request.app.state.active_requests -= 1
