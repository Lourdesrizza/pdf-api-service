import asyncio
import logging
import sys
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.clients.base import request_id_context
from app.clients.documents import DocumentClient
from app.clients.extractor import ExtractorClient
from app.config import get_settings
from app.errors import APIError, install_handlers
from app.schemas import ErrorResponse, ProcessResponse
from app.services.orchestrator import Orchestrator
from app.validation import receive_pdf

settings = get_settings()
logging.basicConfig(
    stream=sys.stdout,
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("pdf_api")

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
    for status in (400, 413, 415, 422, 500, 502, 503, 504)
}


def _is_valid_request_id(value: str) -> bool:
    return bool(value) and len(value) <= 128 and value.isascii() and all(
        32 <= ord(character) < 127 for character in value
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    timeout = httpx.Timeout(
        connect=5.0,
        read=settings.extractor_timeout_seconds,
        write=10.0,
        pool=5.0,
    )
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        documents = DocumentClient(
            client,
            settings.document_service_url,
            settings.document_timeout_seconds,
        )
        extractor = ExtractorClient(
            client,
            settings.extractor_url,
            settings.extractor_timeout_seconds,
        )
        app.state.orchestrator = Orchestrator(documents, extractor)
        app.state.extractor = extractor
        app.state.documents = documents
        app.state.active_requests = 0
        app.state.active_lock = asyncio.Lock()
        yield


app = FastAPI(title="PDF API Service", version="0.1.0", lifespan=lifespan)
install_handlers(app)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "")
    if not _is_valid_request_id(request_id):
        request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    token = request_id_context.set(request_id)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled request failure request_id=%s", request_id)
        raise
    finally:
        request_id_context.reset(token)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api"}


@app.get("/ready", responses={503: {"model": ErrorResponse}})
async def ready(request: Request):
    timeout = settings.ready_check_timeout_seconds
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


@app.post(
    "/process",
    response_model=ProcessResponse,
    openapi_extra=PROCESS_OPENAPI_EXTRA,
    responses=PROCESS_ERROR_RESPONSES,
)
async def process(request: Request):
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
        pdf, filename = await receive_pdf(request, settings.max_upload_bytes)
        return await request.app.state.orchestrator.process(pdf, filename)
    finally:
        if limit > 0:
            async with request.app.state.active_lock:
                request.app.state.active_requests -= 1
