import hashlib
import asyncio
import threading

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import main
from app.checksum import calculate_checksum
from app.clients import circuit
from app.config import Settings

PDF = b"%PDF-1.4\nexample"
EXTRACTOR = "http://extractor:8000"
DOCUMENTS = "http://documents:8000"
API_TOKEN = "fake-process-client-token-only-12345"


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
    return {"id": "abc123", "checksum": calculate_checksum(PDF), "filename": "document.pdf", "content": "# text", "page_count": 1, **overrides}


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


def test_open_extractor_returns_controlled_503_and_existing_pdf_still_works(client, monkeypatch):
    monkeypatch.setattr(circuit, "monotonic", lambda: 0)
    headers = {"Content-Type": "application/pdf", "X-Request-ID": "open-extractor"}
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        lookup = documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        extract = extractor.post("/extract").mock(return_value=httpx.Response(500))
        for _ in range(3):
            assert client.post("/process", content=PDF, headers=headers).status_code == 502

        rejected = client.post("/process", content=PDF, headers=headers)
        assert rejected.status_code == 503
        assert rejected.json() == {
            "error": "upstream_unavailable",
            "detail": "El servicio extractor no está disponible.",
        }
        assert rejected.headers["Retry-After"] == "10"
        assert rejected.headers["X-Request-ID"] == "open-extractor"

        lookup.mock(return_value=httpx.Response(200, json=doc()))
        repeated = client.post("/process", content=PDF, headers=headers)
        assert repeated.status_code == 200
        assert repeated.json()["source"] == "existing"
        assert extract.call_count == 9


@pytest.mark.parametrize("multipart", [False, True])
def test_separate_bearer_tokens_for_new_and_repeated_pdf(monkeypatch, multipart):
    token = "fake-documents-test-token-only-12345"
    monkeypatch.setenv("DOCUMENTS_API_TOKEN", token)
    monkeypatch.setenv("API_REQUIRE_AUTH", "true")
    monkeypatch.setenv("API_ACCESS_TOKEN", API_TOKEN)
    config = Settings(_env_file=None)
    assert token not in repr(config)
    assert API_TOKEN not in repr(config)
    install_settings(
        monkeypatch,
        documents_api_token=config.documents_api_token,
        api_require_auth=config.api_require_auth,
        api_access_token=config.api_access_token,
    )
    checksum = calculate_checksum(PDF)
    with (
        TestClient(main.app) as client,
        respx.mock(base_url=DOCUMENTS) as documents,
        respx.mock(base_url=EXTRACTOR) as extractor,
    ):
        lookup = documents.get(f"/documents/by-checksum/{checksum}").mock(
            side_effect=[httpx.Response(404), httpx.Response(200, json=doc())],
        )
        save = documents.post("/documents").mock(return_value=httpx.Response(201, json=doc()))
        documents_ready = documents.get("/health/ready").mock(return_value=httpx.Response(200))
        extractor_ready = extractor.get("/health/ready").mock(return_value=httpx.Response(200))
        extract = extractor.post("/extract").mock(
            return_value=httpx.Response(200, json={"content": "# text", "page_count": 1}),
        )
        headers = {"Authorization": f"bEaReR  {API_TOKEN}", "X-Request-ID": "documents-auth-test"}
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        if multipart:
            first = client.post("/process", files={"file": ("document.pdf", PDF, "application/pdf")}, headers=headers)
        else:
            first = client.post("/process", content=PDF, headers={**headers, "Content-Type": "application/pdf"})
        repeated = client.post("/process", content=PDF, headers={**headers, "Content-Type": "application/pdf"})

    assert first.status_code == repeated.status_code == 200
    assert first.json()["source"] == "extracted"
    assert repeated.json()["source"] == "existing"
    assert first.json()["checksum"] == repeated.json()["checksum"] == checksum
    assert first.json()["document_id"] == repeated.json()["document_id"] == "abc123"
    assert lookup.call_count == 2
    assert save.call_count == extract.call_count == 1
    for call in [*lookup.calls, *save.calls]:
        assert call.request.headers["authorization"] == f"Bearer {token}"
        assert call.request.headers["x-request-id"] == "documents-auth-test"
    for route in (documents_ready, extractor_ready, extract):
        assert "authorization" not in route.calls.last.request.headers


@pytest.mark.parametrize("authorization", [
    pytest.param([], id="missing"),
    pytest.param(["Bearer fake-process-client-token-only-54321"], id="incorrect"),
    pytest.param([f"Bearer {API_TOKEN}", f"Bearer {API_TOKEN}"], id="duplicate"),
    pytest.param([f"Bearer {API_TOKEN}, Bearer {API_TOKEN}"], id="combined"),
    pytest.param([f"Basic {API_TOKEN}"], id="wrong-scheme"),
    pytest.param(["Bearer"], id="missing-token"),
    pytest.param([b"Bearer \xff"], id="non-ascii"),
])
async def test_process_auth_rejects_before_admission_or_body(monkeypatch, caplog, authorization):
    monkeypatch.setenv("API_REQUIRE_AUTH", "true")
    monkeypatch.setenv("API_ACCESS_TOKEN", API_TOKEN)
    config = Settings(_env_file=None)
    install_settings(
        monkeypatch, api_require_auth=True, api_access_token=config.api_access_token,
        max_concurrent_requests=1,
    )

    async def body():
        pytest.fail("El cuerpo de un pedido sin autorización no debe leerse")
        yield PDF

    headers = [("Content-Type", "application/pdf"), *[("Authorization", value) for value in authorization]]
    async with main.lifespan(main.app):
        # A rejected request must never acquire the admission lock.
        monkeypatch.setattr(main.app.state, "active_lock", None)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://api",
        ) as client:
            with respx.mock(assert_all_called=False) as upstream:
                response = await client.post("/process", headers=headers, content=body())
            assert not upstream.calls
        assert main.app.state.active_requests == 0

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"error": "unauthorized", "detail": "Se requiere un token Bearer válido."}
    assert API_TOKEN not in response.text + caplog.text
    assert "fake-process-client-token-only-54321" not in response.text + caplog.text


def test_documents_unauthorized_stops_processing(client, caplog):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(
            return_value=httpx.Response(
                401, headers={"WWW-Authenticate": "Bearer"}, json={"detail": "internal-auth-detail"},
            ),
        )
        result = client.post("/process", content=PDF, headers={"Content-Type": "application/pdf"})
    assert result.status_code == 502
    assert result.json()["error"] == "upstream_error"
    assert "www-authenticate" not in result.headers
    assert "internal-auth-detail" not in result.text + caplog.text
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


def test_extractor_remote_protocol_error_maps_to_502(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        extractor.post("/extract").mock(side_effect=httpx.RemoteProtocolError("connection dropped"))
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 502
    assert set(result.json()) == {"error", "detail"}


def test_document_service_503_maps_to_503(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(503))
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 503
    assert set(result.json()) == {"error", "detail"}
    assert result.headers["retry-after"] == "1"


def test_document_service_remote_protocol_error_maps_to_502(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents:
        documents.get(f"/documents/by-checksum/{checksum}").mock(
            side_effect=httpx.RemoteProtocolError("connection dropped")
        )
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 502
    assert set(result.json()) == {"error", "detail"}


def test_timeout_and_connectivity_mapping(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        extractor.post("/extract").mock(side_effect=httpx.ConnectError("secret host"))
        assert client.post("/process", content=PDF, headers={"content-type": "application/pdf"}).status_code == 502
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
    assert result.status_code == 502


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


def test_invalid_request_id_is_replaced(client):
    result = client.get("/health", headers={"X-Request-ID": "x" * 129})
    request_id = result.headers["X-Request-ID"]
    assert len(request_id) == 32
    assert all(32 <= ord(char) < 127 for char in request_id)


def test_extractor_retry_after_is_forwarded_and_validated(client):
    checksum = calculate_checksum(PDF)
    with respx.mock(base_url=DOCUMENTS) as documents, respx.mock(base_url=EXTRACTOR) as extractor:
        documents.get(f"/documents/by-checksum/{checksum}").mock(return_value=httpx.Response(404))
        extractor.post("/extract").mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}))
        result = client.post("/process", content=PDF, headers={"content-type": "application/pdf"})
    assert result.status_code == 503
    assert result.headers["retry-after"] == "7"
