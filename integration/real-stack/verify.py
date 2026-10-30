from pathlib import Path
import hashlib
import json
import os
import re
import time
import httpx

API = "http://api:8000"
PROXY = "http://traefik:80"
EXPECTED = "ISOLATED PDF API EXTRACTION PROOF"
EXPECTED_PAGE_COUNT = int(os.environ.get("PRIMARY_EXPECTED_PAGE_COUNT", "1"))
EXPECTED_TEXT = os.environ.get("PRIMARY_EXPECTED_TEXT", EXPECTED)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def response_json(response, status, label):
    require(response.status_code == status, f"{label}: expected HTTP {status}, received {response.status_code}: {response.text[:500]}")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"{label}: response was not JSON") from exc


def extract_count(client):
    response = client.get("http://extractor:8000/metrics")
    response.raise_for_status()
    total = 0
    for line in response.text.splitlines():
        if not line.startswith("pdf_http_requests_total{"):
            continue
        if 'method="POST"' not in line or 'route="/extract"' not in line:
            continue
        value = line.rsplit(None, 1)[-1]
        total += int(float(value))
    return total


def validate_document(document, checksum, expected_page_count, expected_text):
    require(isinstance(document, dict), "process response must be a JSON object")
    require(document.get("checksum") == checksum, "checksum mismatch")
    require(type(document.get("page_count")) is int and document["page_count"] == expected_page_count, f"expected {expected_page_count} pages")
    require(isinstance(document.get("document_id"), str) and document["document_id"], "missing document_id")
    content = document.get("content")
    require(isinstance(content, str) and content.strip(), "extracted content must be non-empty")
    require(content.startswith("## Página 1\n"), "first-page Markdown heading missing")
    require(f"## Página {expected_page_count}\n" in content, "last-page Markdown heading missing")
    if expected_text:
        require(expected_text in content, "expected extracted text missing")
    require(document.get("source") in ("extracted", "existing"), "invalid source value")


def document_summary(document):
    content = document["content"]
    return {
        "document_id": document["document_id"],
        "checksum": document["checksum"],
        "page_count": document["page_count"],
        "source": document["source"],
        "content_characters": len(content),
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "has_first_page_heading": content.startswith("## Página 1\n"),
        "has_last_page_heading": f"## Página {document['page_count']}\n" in content,
    }


def run():
    pdf = open("/fixtures/proof.pdf", "rb").read()
    concurrent_pdf = open("/fixtures/concurrency.pdf", "rb").read()
    checksum = hashlib.sha256(pdf).hexdigest()
    concurrent_checksum = hashlib.sha256(concurrent_pdf).hexdigest()
    headers = {"Content-Type": "application/pdf", "X-Filename": "prueba.pdf", "X-Request-ID": "integration-primary-proof"}
    concurrent_headers = {"Content-Type": "application/pdf", "X-Filename": "concurrent.pdf"}
    result = {"checksum": checksum, "concurrency_checksum": concurrent_checksum}

    with httpx.Client(timeout=90) as client:
        health = client.get(API + "/health")
        result["health"] = {"status": health.status_code, "body": response_json(health, 200, "health")}
        ready = client.get(API + "/ready", headers={"X-Request-ID": "integration-readiness-proof"})
        ready_body = response_json(ready, 200, "ready")
        require(ready_body.get("dependencies") == {"extractor": "ok", "documents": "ok"}, "readiness must show extractor and documents ready")
        result["ready"] = {"status": ready.status_code, "body": ready_body}

        before = extract_count(client)
        first_started = time.perf_counter()
        first_response = client.post(API + "/process", content=pdf, headers=headers)
        first_duration_ms = round((time.perf_counter() - first_started) * 1000, 3)
        first = response_json(first_response, 200, "first process")
        validate_document(first, checksum, EXPECTED_PAGE_COUNT, EXPECTED_TEXT)
        require(first["source"] == "extracted", "first request must extract a new PDF")
        after_first = extract_count(client)
        require(after_first == before + 1, f"POST /extract counter must increase by one: {before} -> {after_first}")

        second_started = time.perf_counter()
        second_response = client.post(API + "/process", content=pdf, headers=headers)
        second_duration_ms = round((time.perf_counter() - second_started) * 1000, 3)
        second = response_json(second_response, 200, "second process")
        validate_document(second, checksum, EXPECTED_PAGE_COUNT, EXPECTED_TEXT)
        require(second["source"] == "existing", "second request must use the stored document")
        require(second["document_id"] == first["document_id"], "same PDF returned a different document ID")
        require(second["content"] == first["content"], "stored content differs from first extracted content")
        after_second = extract_count(client)
        require(after_second == after_first, f"repeated request must not call extractor: {after_first} -> {after_second}")

        multipart_started = time.perf_counter()
        multipart_response = client.post(
            API + "/process",
            files={"file": ("prueba.pdf", pdf, "application/pdf")},
            headers={"X-Request-ID": "integration-primary-multipart"},
        )
        multipart_duration_ms = round((time.perf_counter() - multipart_started) * 1000, 3)
        multipart = response_json(multipart_response, 200, "multipart process")
        validate_document(multipart, checksum, EXPECTED_PAGE_COUNT, EXPECTED_TEXT)
        require(multipart["source"] == "existing", "multipart request must use the stored document")
        require(multipart["document_id"] == first["document_id"], "multipart request returned a different document ID")
        require(multipart["content"] == first["content"], "multipart content differs from first extracted content")
        after_multipart = extract_count(client)
        require(after_multipart == after_second, f"multipart request must not call extractor: {after_second} -> {after_multipart}")
        result["primary_flow"] = {
            "first": {"status": first_response.status_code, "duration_ms": first_duration_ms, "document": document_summary(first)},
            "second": {"status": second_response.status_code, "duration_ms": second_duration_ms, "document": document_summary(second)},
            "multipart": {"status": multipart_response.status_code, "duration_ms": multipart_duration_ms, "document": document_summary(multipart)},
            "extract_post_total": {"before": before, "after_first": after_first, "after_second": after_second, "after_multipart": after_multipart},
        }

        invalid_api_response = client.post(API + "/process", content=b"not a PDF", headers=headers)
        invalid_api = response_json(invalid_api_response, 400, "API signature validation")
        require(set(invalid_api) == {"error", "detail"} and invalid_api.get("error") == "invalid_pdf", "API-boundary 400 must use the stable error JSON")
        after_invalid_api = extract_count(client)
        require(after_invalid_api == after_second, "API-boundary rejection must not call /extract")

        malformed_pdf = b"%PDF-1.4\nThis is not a valid PDF object tree.\n%%EOF\n"
        malformed_response = client.post(API + "/process", content=malformed_pdf, headers={"Content-Type": "application/pdf", "X-Filename": "corrupt.pdf", "X-Request-ID": "integration-extractor-rejection"})
        malformed = response_json(malformed_response, 422, "extractor PDF rejection")
        require(set(malformed) == {"error", "detail"} and malformed.get("error") == "pdf_rejected", "extractor rejection must be translated to the public 422 contract")
        after_malformed = extract_count(client)
        require(after_malformed == after_invalid_api + 1, "signature-valid malformed PDF must reach extractor exactly once")
        result["invalid_inputs"] = {
            "invalid_signature": {"status": invalid_api_response.status_code, "body": invalid_api, "extract_post_total": after_invalid_api, "layer": "API validation; extractor counter unchanged"},
            "malformed_pdf": {"status": malformed_response.status_code, "body": malformed, "extract_post_total": after_malformed, "layer": "extractor rejection translated to API 422"},
        }

        # API access through an exclusive, internal file-provider Traefik.
        proxied_health_response = client.get(PROXY + "/health", headers={"Host": "api.test"})
        proxied_health = response_json(proxied_health_response, 200, "Traefik /health")
        proxied_ready_response = client.get(PROXY + "/ready", headers={"Host": "api.test"})
        proxied_ready = response_json(proxied_ready_response, 200, "Traefik /ready")
        require(proxied_ready.get("dependencies") == {"extractor": "ok", "documents": "ok"}, "proxy readiness mismatch")
        proxy_before = extract_count(client)
        proxy_existing_response = client.post(PROXY + "/process", content=pdf, headers={**headers, "Host": "api.test"})
        proxy_existing = response_json(proxy_existing_response, 200, "Traefik /process existing")
        require(proxy_existing.get("source") == "existing" and proxy_existing.get("document_id") == first.get("document_id"), "Traefik did not route to the same API/document state")
        proxy_after = extract_count(client)
        require(proxy_after == proxy_before, "proxy request for stored PDF unexpectedly called extractor")
        result["exclusive_traefik"] = {
            "health": {"status": proxied_health_response.status_code, "body": proxied_health},
            "ready": {"status": proxied_ready_response.status_code, "body": proxied_ready},
            "process": {"status": proxy_existing_response.status_code, "document": document_summary(proxy_existing)},
            "extract_post_total": {"before": proxy_before, "after": proxy_after},
            "scope": "internal Compose network; file provider; no Docker socket, dashboard or published ports",
        }

        # Two near-simultaneous requests with a distinct valid PDF exercise Documents uniqueness.
        concurrency_before = extract_count(client)
        import asyncio
        async def submit():
            async with httpx.AsyncClient(timeout=90) as async_client:
                return await async_client.post(API + "/process", content=concurrent_pdf, headers=concurrent_headers)
        async def run_concurrent():
            return await asyncio.gather(submit(), submit())
        concurrent_responses = asyncio.run(run_concurrent())
        concurrent_docs = []
        for response in concurrent_responses:
            body = response_json(response, 200, "concurrent process")
            validate_document(body, concurrent_checksum, 1, "CONCURRENT API DOCUMENT")
            concurrent_docs.append(body)
        require(concurrent_docs[0]["document_id"] == concurrent_docs[1]["document_id"], "concurrent requests returned different IDs")
        require({item["source"] for item in concurrent_docs} == {"existing", "extracted"}, "concurrent results must reflect one creation and one duplicate")
        concurrency_after = extract_count(client)
        result["concurrent_same_pdf"] = {
            "responses": [{"status": response.status_code, "body": body} for response, body in zip(concurrent_responses, concurrent_docs)],
            "extract_post_total": {"before": concurrency_before, "after": concurrency_after},
            "extraction_count_assertion": "no single-extraction race requirement; Documents uniqueness and consistent result are required",
        }

        result["direct_counts"] = {
            "documents_checksum_reads": checksum,
            "extract_post_total_final": extract_count(client),
            "invalid_api_signature_did_not_increment": True,
            "extractor_rejection_incremented": True,
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
