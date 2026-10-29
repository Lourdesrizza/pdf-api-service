import json
from pathlib import Path

import httpx
import pytest
from fastapi import Response
from pydantic import ValidationError
from starlette.requests import Request

from app.checksum import calculate_checksum
from app.clients.base import map_upstream_status, request_id_context
from app.clients.documents import DocumentClient
from app.clients.extractor import ExtractorClient
from app.errors import APIError
from app.services.orchestrator import Orchestrator
from app.validation import receive_pdf
from tests.fakes.documents import CreateDocument, app as documents_app, create, records


@pytest.mark.parametrize("count", [True, "1", None, 0, -1])
def test_fake_rejects_pages(count):
    with pytest.raises(ValidationError):
        CreateDocument(checksum="a" * 64, content="", page_count=count)


@pytest.mark.parametrize("extra", [{"extracted_text": "old"}, {"extra": 1}])
def test_fake_rejects_extra(extra):
    with pytest.raises(ValidationError):
        CreateDocument(checksum="a" * 64, content="", page_count=1, **extra)


def test_fake_duplicate():
    records.clear()
    item = CreateDocument(checksum="a" * 64, content="", page_count=1)

    first = create(item, Response())
    response = Response()
    second = create(item, response)

    assert response.status_code == 200
    assert first == second
    assert first["created_at"]
    assert len(records) == 1


@pytest.mark.parametrize("status,expected", [(400, 422), (413, 413), (415, 422), (429, 503), (503, 503)])
@pytest.mark.parametrize("body", [b'{"detail":"SECRET"}', b"[]", b"SECRET"])
def test_error_privacy(status, expected, body):
    response = httpx.Response(
        status,
        content=body,
        headers={"content-type": "application/problem+json"},
    )

    with pytest.raises(APIError) as caught:
        map_upstream_status(response, "extractor", extractor=True)

    assert caught.value.status_code == expected
    assert "SECRET" not in caught.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("status,created", [(200, False), (201, True)])
async def test_creation_result(status, created):
    payload = {
        "checksum": "a" * 64,
        "filename": "test.pdf",
        "content": "",
        "page_count": 1,
    }

    async def handler(request):
        assert json.loads(request.content) == payload
        return httpx.Response(status, json={"id": "id", **payload})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await DocumentClient(client, "http://documents").create(**payload)

    assert result.created is created
    assert result.document.id == "id"
    assert result.document.checksum == payload["checksum"]


async def receive(body: bytes, content_type: str, limit: int) -> tuple[bytes, str]:
    parts = [body[:3], body[3:100], body[100:]]
    events = iter(
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < 2,
        }
        for index, chunk in enumerate(parts)
    )

    async def read_events():
        return next(events)

    scope = {
        "type": "http",
        "headers": [(b"content-type", content_type.encode())],
    }
    request = Request(scope, read_events)
    return await receive_pdf(request, limit)


@pytest.mark.asyncio
async def test_size_and_checksum():
    limit = 20 * 1024 * 1024
    pdf = b"%PDF-" + b"x" * (limit - 5)
    received_pdf, _ = await receive(pdf, "application/pdf", limit)
    assert len(received_pdf) == limit

    with pytest.raises(APIError) as too_large:
        await receive(pdf + b"x", "application/pdf", limit)
    assert too_large.value.status_code == 413

    small_pdf = b"%PDF-1.4 fixture"
    multipart = (
        b'--b\r\nContent-Disposition: form-data; name="file"; filename="x.pdf"\r\n\r\n'
        + small_pdf
        + b"\r\n--b--\r\n"
    )
    received_pdf, _ = await receive(
        multipart,
        "multipart/form-data; boundary=b",
        len(multipart),
    )
    assert calculate_checksum(received_pdf) == calculate_checksum(small_pdf)

    with pytest.raises(APIError) as multipart_too_large:
        await receive(multipart, "multipart/form-data; boundary=b", len(multipart) - 1)
    assert multipart_too_large.value.status_code == 413


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,source",
    [(200, "existing"), (201, "extracted"), (409, "existing")],
)
async def test_orchestrator_creation_paths(status, source):
    pdf = b"%PDF-test"
    checksum = calculate_checksum(pdf)
    lookups = 0
    document = {
        "id": "stable",
        "checksum": checksum,
        "content": "",
        "page_count": 1,
    }

    async def handler(request):
        nonlocal lookups
        if request.method == "GET":
            lookups += 1
            if lookups == 1:
                return httpx.Response(404)
            return httpx.Response(200, json=document)
        return httpx.Response(status, json=document)

    class StubExtractor:
        async def extract(self, _pdf):
            return "", 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        orchestrator = Orchestrator(
            DocumentClient(client, "http://documents"),
            StubExtractor(),
        )
        result = await orchestrator.process(pdf, "x.pdf")

    assert result.source == source
    assert result.document_id == "stable"
    assert result.checksum == checksum


@pytest.mark.parametrize(
    "patch",
    [
        {"content": None},
        {"page_count": True},
        {"page_count": 0},
        {"checksum": "b" * 64},
        {"id": 5},
    ],
)
def test_invalid_document_response(patch):
    body = {
        "id": "id",
        "checksum": "a" * 64,
        "content": "",
        "page_count": 1,
        **patch,
    }

    with pytest.raises(APIError) as caught:
        DocumentClient._parse(httpx.Response(200, json=body), "a" * 64)

    assert caught.value.status_code == 502


@pytest.mark.asyncio
async def test_fake_roundtrip_with_counter():
    pdf = Path(__file__).with_name("fixtures").joinpath("sample.pdf").read_bytes()
    records.clear()
    extractor_calls = 0
    documents_transport = httpx.ASGITransport(app=documents_app)
    request_id = "api-trace-unit-test"
    token = request_id_context.set(request_id)

    async def route(request):
        nonlocal extractor_calls
        assert request.headers["X-Request-ID"] == request_id
        if request.url.host == "extractor":
            extractor_calls += 1
            assert request.content == pdf
            assert request.headers["content-type"] == "application/pdf"
            return httpx.Response(200, json={"content": "Fake text", "page_count": 1})
        return await documents_transport.handle_async_request(request)

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
            orchestrator = Orchestrator(
                DocumentClient(client, "http://documents"),
                ExtractorClient(client, "http://extractor"),
            )
            first = await orchestrator.process(pdf, "sample.pdf")
            second = await orchestrator.process(pdf, "sample.pdf")
    finally:
        request_id_context.reset(token)

    assert first.source == "extracted"
    assert second.source == "existing"
    assert first.document_id == second.document_id
    assert first.checksum == second.checksum
    assert extractor_calls == 1
    assert len(records) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"content": None, "page_count": 1},
        {"content": "", "page_count": True},
        {"content": "", "page_count": 0},
        [],
    ],
)
async def test_invalid_extractor_stops_persistence(payload):
    persistence_requests = []

    async def handler(request):
        if request.method == "GET":
            return httpx.Response(404)
        if request.url.host == "extractor":
            return httpx.Response(200, json=payload)
        persistence_requests.append(request)
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        orchestrator = Orchestrator(
            DocumentClient(client, "http://documents"),
            ExtractorClient(client, "http://extractor"),
        )
        with pytest.raises(APIError) as caught:
            await orchestrator.process(b"%PDF-test", "test.pdf")

    assert caught.value.status_code == 502
    assert not persistence_requests


@pytest.mark.asyncio
async def test_unrecoverable_conflict():
    async def handler(request):
        if request.method == "GET":
            return httpx.Response(404)
        if request.url.host == "extractor":
            return httpx.Response(200, json={"content": "", "page_count": 1})
        return httpx.Response(409)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        orchestrator = Orchestrator(
            DocumentClient(client, "http://documents"),
            ExtractorClient(client, "http://extractor"),
        )
        with pytest.raises(APIError) as caught:
            await orchestrator.process(b"%PDF-test", "test.pdf")

    assert caught.value.status_code == 502


@pytest.mark.parametrize(
    "value,expected",
    [
        ("5", "5"),
        ("86400", "86400"),
        ("", "1"),
        ("0", "1"),
        ("86401", "1"),
        ("abc", "1"),
        ("999999999999999999999999999999999999", "1"),
    ],
)
def test_retry_after_is_bounded_and_defaults(value, expected):
    with pytest.raises(APIError) as caught:
        map_upstream_status(
            httpx.Response(503, headers={"Retry-After": value}),
            "extractor",
            extractor=True,
        )

    assert caught.value.status_code == 503
    assert caught.value.headers["Retry-After"] == expected
