from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app.config import Settings
from app.main import app


def test_metrics_are_disabled_without_a_token(monkeypatch):
    settings = Settings(_env_file=None, metrics_api_token="")
    monkeypatch.setattr(app.state, "settings", settings)

    with TestClient(app) as client:
        assert client.get("/metrics").status_code == 404


def test_protected_metrics_count_process_responses(monkeypatch):
    token = "a" * 32
    settings = Settings(_env_file=None, metrics_api_token=token, api_require_auth=False)
    monkeypatch.setattr(app.state, "settings", settings)

    with TestClient(app) as client:
        process = AsyncMock(return_value={
            "document_id": "test-id",
            "checksum": "abc",
            "content": "extracted text",
            "page_count": 1,
            "source": "extracted",
        })
        monkeypatch.setattr(app.state.orchestrator, "process", process)

        assert client.get("/health").status_code == 200
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer invalid"}).status_code == 401
        assert client.post("/process", content=b"invalid").status_code == 415
        assert client.post(
            "/process", content=b"%PDF-1.7", headers={"Content-Type": "application/pdf"},
        ).status_code == 200

        response = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
        assert response.headers["cache-control"] == "no-store"
        assert token not in response.text
        assert "extracted text" not in response.text
        metrics = {
            (sample.name, tuple(sample.labels.items())): sample.value
            for family in text_string_to_metric_families(response.text)
            for sample in family.samples
        }
        counts = {key: value for key, value in metrics.items() if key[0].endswith("requests_total")}
        assert counts == {
            ("pdf_api_process_requests_total", (("status_code", "200"),)): 1,
            ("pdf_api_process_requests_total", (("status_code", "415"),)): 1,
        }
        assert metrics[("pdf_api_process_duration_seconds_count", ())] == 2
        assert metrics[("pdf_api_process_duration_seconds_sum", ())] > 0
