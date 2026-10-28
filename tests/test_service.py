import hashlib
import asyncio
import threading

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import main
from app.checksum import calculate_checksum

PDF = b"%PDF-1.4\nexample"
EXTRACTOR = "http://extractor:8000"
DOCUMENTS = "http://documents:8000"


def install_settings(monkeypatch, **kwargs):
    for name, value in {
        "extractor_url": EXTRACTOR,
        "document_service_url": DOCUMENTS,
        "max_upload_bytes": 1024,
        "max_concurrent_requests": 0,
        "extractor_timeout_seconds": 1,
        "document_timeout_seconds": 1,
        "ready_check_timeout_seconds": 0.2,
        **kwargs,
    }.items():
        monkeypatch.setattr(main.settings, name, value)


def doc(**overrides):
    return {"id": "abc123", "checksum": calculate_checksum(PDF), "filename": "document.pdf", "content": "# text", **overrides}


@pytest.fixture
def client(monkeypatch):
    install_settings(monkeypatch)
    with TestClient(main.app) as client:
        yield client


def test_checksum_deterministic():
    assert calculate_checksum(PDF) == hashlib.sha256(PDF).hexdigest()


def test_health_openapi_and_ready(client):
    assert client.get("/health").json() == {"status": "ok", "service": "api"}
    with respx.mock(base_url=EXTRACTOR) as extractor, respx.mock(base_url=DOCUMENTS) as documents:
        extractor.get("/health/ready").mock(return_value=httpx.Response(200))
        documents.get("/health/ready").mock(return_value=httpx.Response(200))
        assert client.get("/ready").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/process", "/health", "/ready"}.issubset(paths)


@pytest.mark.parametrize(("headers", "body", "status"), [
    ({"content-type": "application/pdf"}, b"", 400),
    ({"content-type": "application/pdf"}, b"%PDF-" + b"x" * 1024, 413),
    ({"content-type": "text/plain"}, b"x", 415),
    ({"content-type": "application/pdf"}, b"not-pdf", 400),
])
def test_frontier_validation(client, headers, body, status):
    assert client.post("/process", content=body, headers=headers).status_code == status


def test_existing_skips_extractor(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(200, json=doc()))
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 200
    assert result.json()["source"] == "existing"
    assert result.json()["content"] == "# text"
    assert not extractor.calls


@pytest.mark.parametrize("multipart", [False, True])
def test_extracted_and_multipart_same_result(client, multipart):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        extractor.post("/extract").mock(return_value=httpx.Response(200, json={"content": "# new", "page_count": 1}))
        documents.post("/documents").mock(return_value=httpx.Response(201, json=doc(content="# new", page_count=1)))
        if multipart:
            result = client.post("/process", files={"file": ("test.pdf", PDF, "application/pdf")})
        else:
            result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 200
    assert result.json()["source"] == "extracted"
    assert result.json()["content"] == "# new"
    assert result.json()["page_count"] == 1


@pytest.mark.parametrize(("response", "expected"), [
    (httpx.Response(400, json={"detail": "PDF protegido"}), 422),
    (httpx.Response(500), 502),
])
def test_extractor_error_mapping(client, response, expected):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        extractor.post("/extract").mock(return_value=response)
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == expected
    assert set(result.json()) == {"error", "detail"}


def test_extractor_429_maps_to_503(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        extractor.post("/extract").mock(return_value=httpx.Response(429))
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 503
    assert set(result.json()) == {"error", "detail"}
    assert result.headers["retry-after"] == "1"


def test_extractor_503_maps_to_503(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        extractor.post("/extract").mock(return_value=httpx.Response(503))
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 503
    assert set(result.json()) == {"error", "detail"}
    assert result.headers["retry-after"] == "1"


def test_extractor_500_remains_502(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        extractor.post("/extract").mock(return_value=httpx.Response(500))
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 502
    assert set(result.json()) == {"error", "detail"}


def test_extractor_remote_protocol_error_maps_to_503(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        extractor.post("/extract").mock(side_effect=httpx.RemoteProtocolError("connection dropped"))
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 503
    assert set(result.json()) == {"error", "detail"}


def test_document_service_503_maps_to_503(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(503))
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 503
    assert set(result.json()) == {"error", "detail"}
    assert result.headers["retry-after"] == "1"


def test_document_service_remote_protocol_error_maps_to_503(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents:
        documents.get(f"/documents/by-checksum/{checksum}").mock(
            side_effect=httpx.RemoteProtocolError("connection dropped")
        )
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 503
    assert set(result.json()) == {"error", "detail"}


def test_timeout_and_connectivity_mapping(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        extractor.post("/extract").mock(side_effect=httpx.ConnectError("secret host"))
        assert client.post("/process", content=PDF, headers={"content-type": "application/pdf"}).status_code == 503
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        extractor.post("/extract").mock(side_effect=httpx.ReadTimeout("internal"))
        assert client.post("/process", content=PDF, headers={"content-type": "application/pdf"}).status_code == 504


def test_conflict_rereads_existing(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        lookup = documents.get(f"/documents/by-checksum/{checksum}").mock(side_effect=[httpx.Response(404), httpx.Response(200, json=doc())])
        extractor.post("/extract").mock(return_value=httpx.Response(200, json={"content": "# new", "page_count": 1}))
        documents.post("/documents").mock(return_value=httpx.Response(409))
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.json()["source"] == "existing"
    assert lookup.call_count == 2


def test_document_service_down(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents:
        documents.get(f"/documents/by-checksum/{checksum}").mock(side_effect=httpx.ConnectError("hidden"))
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 503


def test_ready_degraded(client):
    with respx.mock(base_url=EXTRACTOR) as extractor, respx.mock(base_url=DOCUMENTS) as documents:
        extractor.get("/health/ready").mock(return_value=httpx.Response(503))
        documents.get("/health/ready").mock(return_value=httpx.Response(200))
        result = client.get("/ready")
    assert result.status_code == 503
    assert result.json()["dependencies"]["extractor"] == "unavailable"


def test_backpressure_rejects_second_request(monkeypatch):
    install_settings(monkeypatch, max_concurrent_requests=1)
    entered = threading.Event()
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        async def slow(request):
            entered.set()
            await asyncio.sleep(0.5)
            return httpx.Response(200, json={"content": "text", "page_count": 1})
        extractor.post("/extract").mock(side_effect=slow)
        documents.post("/documents").mock(return_value=httpx.Response(201, json=doc()))
        with TestClient(main.app) as c:
            result_holder = []
            thread = threading.Thread(target=lambda: result_holder.append(c.post("/process", content=PDF, headers={"content-type": "application/pdf"})))
            thread.start()
            assert entered.wait(timeout=1)
            second = c.post("/process", content=PDF, headers={"content-type": "application/pdf"})
            thread.join(timeout=2)
    assert second.status_code == 503
    assert second.headers["retry-after"] == "1"
