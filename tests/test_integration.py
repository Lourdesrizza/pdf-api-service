import os
import hashlib
from pathlib import Path
import httpx
import pytest

@pytest.mark.integration
@pytest.mark.skipif(os.getenv("API_DEDICATED_TEST_ENV")!="1" or not os.getenv("API_TEST_URL"),reason="requires explicit dedicated real stack")
def test_live_process_round_trip():
    pdf=Path(__file__).with_name("fixtures").joinpath("sample.pdf").read_bytes()
    checksum=hashlib.sha256(pdf).hexdigest()
    url=os.environ["API_TEST_URL"].rstrip("/")+"/process"
    with httpx.Client(timeout=60) as client:
        first=client.post(url,content=pdf,headers={"Content-Type":"application/pdf"})
        assert first.status_code==200
        a=first.json()
        assert a["source"]=="extracted", "Fixture must be absent in dedicated database"
        assert a["checksum"]==checksum and a["document_id"]
        assert a["page_count"]==1 and "PDF API integration fixture" in a["content"]
        second=client.post(url,content=pdf,headers={"Content-Type":"application/pdf"})
        assert second.status_code==200
        b=second.json()
        assert b["source"]=="existing"
        assert b["document_id"]==a["document_id"] and b["checksum"]==checksum
    # Separate extractor instrumentation is required to prove no second extraction.
