import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from app import main
from app.clients.documents import DocumentClient
from app.clients.extractor import ExtractorClient
from app.config import Settings
from app.errors import APIError
from app.validation import parse_multipart, receive_pdf


@pytest.mark.parametrize("field,value", [
    ("port", 0), ("port", 65536), ("max_upload_bytes", 0),
    ("max_concurrent_requests", -1),
    *[(name, value) for name in (
        "body_timeout_seconds", "extractor_timeout_seconds",
        "document_timeout_seconds", "ready_check_timeout_seconds",
    ) for value in (0, -1, float("inf"), float("nan"))],
    ("extractor_url", "ftp://host"), ("document_service_url", "http://"),
    ("extractor_url", "http://user:secret@host"),
])
def test_invalid_settings(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_local_and_service_urls():
    config = Settings(_env_file=None, extractor_url="http://localhost:8001",
                      document_service_url="https://documents:8000", max_concurrent_requests=0)
    assert config.extractor_url == "http://localhost:8001"


def test_invalid_documents_token_is_redacted(monkeypatch):
    token = "fake invalid token"
    monkeypatch.setenv("DOCUMENTS_API_TOKEN", token)
    with pytest.raises(ValidationError, match="DOCUMENTS_API_TOKEN") as error:
        Settings(_env_file=None)
    assert token not in str(error.value)


def request_for(receive, headers=()):
    return Request({"type": "http", "headers": [(b"content-type", b"application/pdf"), *headers]}, receive)


@pytest.mark.asyncio
@pytest.mark.parametrize("length,status", [("-1", 400), ("+1", 400), ("1,1", 400),
                                        ("x", 400), ("11", 413), ("9" * 5000, 413)])
async def test_length_rejected_before_receive(length, status):
    async def forbidden():
        pytest.fail("body must not be read")
    with pytest.raises(APIError) as caught:
        await receive_pdf(request_for(forbidden, [(b"content-length", length.encode())]), 10)
    assert caught.value.status_code == status


@pytest.mark.asyncio
async def test_actual_chunks_override_underreported_length():
    events = iter([{"type": "http.request", "body": b"%PDF-", "more_body": True},
                   {"type": "http.request", "body": b"123456", "more_body": False}])
    async def receive():
        return next(events)
    with pytest.raises(APIError) as caught:
        await receive_pdf(request_for(receive, [(b"content-length", b"1")]), 10)
    assert caught.value.status_code == 413


def multipart(pdf, name="x.pdf"):
    return (f'--b\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n\r\n'.encode()
            + pdf + b"\r\n--b--\r\n")


@pytest.mark.parametrize("pdf", [b"%PDF-\x00\xff\x80\r\n", b"%PDF-\n\n", b"%PDF-\r", bytes(range(256))])
def test_multipart_preserves_binary(pdf):
    assert parse_multipart(multipart(pdf), "multipart/form-data; boundary=b")[0] == pdf


@pytest.mark.parametrize("body,content_type", [
    (multipart(b"%PDF-"), "multipart/form-data"),
    (multipart(b"%PDF-")[:-9], "multipart/form-data; boundary=b"),
    (multipart(b"%PDF-").replace(b'--b--', b'--b\r\nContent-Disposition: form-data; name="file"\r\n\r\nx\r\n--b--'), "multipart/form-data; boundary=b"),
    (multipart(b"%PDF-").replace(b'name="file"', b'name="other"'), "multipart/form-data; boundary=b"),
    (multipart(b"%PDF-").replace(b'\r\n\r\n', b'\r\nContent-Transfer-Encoding: base64\r\n\r\n'), "multipart/form-data; boundary=b"),
    (multipart(b"%PDF-").replace(b'\r\n\r\n', b'\r\nContent-Type: multipart/mixed; boundary=c\r\n\r\n'), "multipart/form-data; boundary=b"),
])
def test_malformed_multipart(body, content_type):
    with pytest.raises(APIError) as caught:
        parse_multipart(body, content_type)
    assert caught.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("name,expected", [("   ", "document.pdf"), ("../x.pdf", "x.pdf"),
                                          ("x" * 300 + ".pdf", "x" * 255), ("x.txt", "document.pdf")])
async def test_filename_contract(name, expected):
    async def receive():
        return {"type": "http.request", "body": b"%PDF-", "more_body": False}
    _, filename = await receive_pdf(request_for(receive, [(b"x-filename", name.encode())]), 100)
    assert filename == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "cancel", "error", "success"])
async def test_admission_released(monkeypatch, mode):
    monkeypatch.setattr(main.settings, "max_concurrent_requests", 1)
    monkeypatch.setattr(main.settings, "body_timeout_seconds", .02)
    entered = asyncio.Event()
    class Orchestrator:
        async def process(self, *_):
            return {"ok": True}
    async def receive():
        entered.set()
        if mode in ("timeout", "cancel"):
            await asyncio.Event().wait()
        return {"type": "http.request", "body": b"bad" if mode == "error" else b"%PDF-", "more_body": False}
    async with main.lifespan(main.app):
        main.app.state.orchestrator = Orchestrator()
        request = request_for(receive)
        request.scope["app"] = main.app
        task = asyncio.create_task(main.process(request))
        await entered.wait()
        if mode in ("timeout", "cancel"):
            with pytest.raises(APIError) as saturated:
                await main.process(request)
            assert saturated.value.status_code == 503
            assert saturated.value.headers["Retry-After"] == "1"
        if mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif mode in ("timeout", "error"):
            with pytest.raises(APIError) as failure:
                await task
            assert failure.value.status_code == (408 if mode == "timeout" else 400)
        else:
            assert await task == {"ok": True}
        assert main.app.state.active_requests == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202, 204, 206, 301])
async def test_unexpected_success_status(status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
        status, json={"content": "", "page_count": 1, "id": "id", "checksum": "a" * 64}))) as client:
        for operation in (ExtractorClient(client, "http://extractor").extract(b"%PDF-"),
                          DocumentClient(client, "http://documents").find_by_checksum("a" * 64)):
            with pytest.raises(APIError) as caught:
                await operation
            assert caught.value.status_code == 502


@pytest.mark.asyncio
async def test_documents_413_stays_502():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(413, text="SECRET"))) as client:
        with pytest.raises(APIError) as caught:
            await DocumentClient(client, "http://documents").create(
                checksum="a" * 64, filename="x.pdf", content="large", page_count=1)
    assert caught.value.status_code == 502
    assert "SECRET" not in caught.value.detail


def test_500_has_request_id_without_sensitive_logs(caplog):
    class Broken:
        async def process(self, *_):
            raise RuntimeError("SECRET PDF MARKDOWN")
    with TestClient(main.app, raise_server_exceptions=False) as client:
        main.app.state.orchestrator = Broken()
        response = client.post("/process", content=b"%PDF-", headers={
            "Content-Type": "application/pdf", "X-Request-ID": "test-500"})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "test-500"
    assert response.json()["error"] == "internal_error"
    assert "SECRET" not in caplog.text


@pytest.mark.asyncio
async def test_slow_body_public_json_and_openapi(monkeypatch):
    monkeypatch.setattr(main.settings, "body_timeout_seconds", .02)
    monkeypatch.setattr(main.settings, "max_concurrent_requests", 1)
    async def slow():
        yield b"%PDF-"
        await asyncio.sleep(1)
    async with main.lifespan(main.app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://api") as client:
            response = await client.post("/process", content=slow(), headers={"Content-Type": "application/pdf"})
            assert response.status_code == 408
            assert set(response.json()) == {"error", "detail"}
            assert response.headers["X-Request-ID"]
            assert main.app.state.active_requests == 0
            schema = (await client.get("/openapi.json")).json()
            assert "408" in schema['paths']['/process']['post']['responses']


@pytest.mark.asyncio
async def test_upstream_decoding_failure_is_502():
    def corrupt(_):
        raise httpx.DecodingError("SECRET")
    async with httpx.AsyncClient(transport=httpx.MockTransport(corrupt)) as client:
        with pytest.raises(APIError) as caught:
            await ExtractorClient(client, "http://extractor").extract(b"%PDF-")
    assert caught.value.status_code == 502
