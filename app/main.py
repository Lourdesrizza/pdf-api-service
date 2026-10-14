import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.clients.documents import DocumentClient
from app.clients.extractor import ExtractorClient
from app.clients.base import request_id_context
from app.config import get_settings
from app.errors import APIError, install_handlers
from app.schemas import ErrorResponse, ProcessResponse
from app.services.orchestrator import Orchestrator
from app.validation import receive_pdf

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("pdf_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    timeout = httpx.Timeout(connect=5.0, read=settings.extractor_timeout_seconds, write=10.0, pool=5.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        documents = DocumentClient(client, settings.document_service_url, settings.document_timeout_seconds)
        extractor = ExtractorClient(client, settings.extractor_url, settings.extractor_timeout_seconds)
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
    request.state.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:128]
    token = request_id_context.set(request.state.request_id)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled request failure request_id=%s", request.state.request_id)
        raise
    finally:
        request_id_context.reset(token)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api"}


@app.get("/ready", responses={503: {"model": ErrorResponse}})
async def ready(request: Request):
    timeout = settings.ready_check_timeout_seconds
    extractor_ok, documents_ok = await asyncio.gather(
        request.app.state.extractor.health(timeout), request.app.state.documents.health(timeout)
    )
    if extractor_ok and documents_ok:
        return {"status": "ready", "dependencies": {"extractor": "ok", "documents": "ok"}}
    return JSONResponse(status_code=503, content={"error": "not_ready", "detail": "Uno o más servicios requeridos no están disponibles.", "dependencies": {"extractor": "ok" if extractor_ok else "unavailable", "documents": "ok" if documents_ok else "unavailable"}})


@app.post("/process", response_model=ProcessResponse, responses={
    400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 415: {"model": ErrorResponse},
    422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}, 504: {"model": ErrorResponse},
})
async def process(request: Request):
    limit = settings.max_concurrent_requests
    if limit > 0:
        async with request.app.state.active_lock:
            if request.app.state.active_requests >= limit:
                raise APIError(503, "api_saturated", "La API está ocupada; reintentá más tarde.", {"Retry-After": "1"})
            request.app.state.active_requests += 1
    try:
        pdf, filename = await receive_pdf(request, settings.max_upload_bytes)
        return await request.app.state.orchestrator.process(pdf, filename)
    finally:
        if limit > 0:
            async with request.app.state.active_lock:
                request.app.state.active_requests -= 1
