"""Resource setup and cleanup for the API process."""

import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.clients.documents import DocumentClient
from app.clients.extractor import ExtractorClient
from app.metrics import ProcessMetrics
from app.services.orchestrator import Orchestrator


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
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
            api_token=settings.documents_api_token,
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
        app.state.process_metrics = (
            ProcessMetrics() if settings.metrics_api_token.get_secret_value() else None
        )
        yield
