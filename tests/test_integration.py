import os

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.mark.integration
@pytest.mark.skipif(not (os.getenv("EXTRACTOR_URL") and os.getenv("DOCUMENT_SERVICE_URL")), reason="requires configured live services")
def test_live_process_round_trip():
    main.settings.extractor_url = os.environ["EXTRACTOR_URL"]
    main.settings.document_service_url = os.environ["DOCUMENT_SERVICE_URL"]
    pdf = b"%PDF-1.4\n% integration smoke test"
    with TestClient(main.app) as client:
        response = client.post("/process", content=pdf, headers={"Content-Type": "application/pdf", "X-Filename": "integration.pdf"})
    assert response.status_code == 200, response.text
    assert response.json()["checksum"]
