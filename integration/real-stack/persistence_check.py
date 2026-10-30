import hashlib
import json
import os
import httpx

expected_pages = int(os.environ.get('PRIMARY_EXPECTED_PAGE_COUNT', '1'))
expected_text = os.environ.get('PRIMARY_EXPECTED_TEXT', 'ISOLATED PDF API EXTRACTION PROOF')

with httpx.Client(timeout=20) as client:
    ready = client.get('http://api:8000/ready')
    if ready.status_code != 200 or ready.json().get('dependencies') != {'extractor': 'ok', 'documents': 'ok'}:
        raise RuntimeError(f'readiness after documents restart failed: {ready.status_code} {ready.text}')
    metrics = client.get('http://extractor:8000/metrics')
    metrics.raise_for_status()
    before = sum(int(float(line.rsplit(None, 1)[-1])) for line in metrics.text.splitlines() if line.startswith('pdf_http_requests_total{') and 'method="POST"' in line and 'route="/extract"' in line)
    pdf = open('/fixtures/proof.pdf', 'rb').read()
    checksum = hashlib.sha256(pdf).hexdigest()
    response = client.post('http://api:8000/process', content=pdf, headers={'Content-Type': 'application/pdf', 'X-Filename': 'prueba.pdf'})
    body = response.json()
    content = body.get('content', '')
    if (
        response.status_code != 200
        or body.get('source') != 'existing'
        or body.get('checksum') != checksum
        or body.get('page_count') != expected_pages
        or not isinstance(content, str)
        or not content.strip()
        or not content.startswith('## Página 1\n')
        or f'## Página {expected_pages}\n' not in content
        or (expected_text and expected_text not in content)
    ):
        raise RuntimeError(f'persistence result mismatch: {response.status_code} {response.text[:500]}')
    metrics_after = client.get('http://extractor:8000/metrics')
    metrics_after.raise_for_status()
    after = sum(int(float(line.rsplit(None, 1)[-1])) for line in metrics_after.text.splitlines() if line.startswith('pdf_http_requests_total{') and 'method="POST"' in line and 'route="/extract"' in line)
    if after != before:
        raise RuntimeError(f'extractor counter changed after documents restart: {before} -> {after}')
    print(json.dumps({
        'ready': ready.json(),
        'after_documents_restart': {
            'status': response.status_code,
            'document_id': body.get('document_id'),
            'checksum': checksum,
            'page_count': body.get('page_count'),
            'source': body.get('source'),
            'content_characters': len(content),
            'content_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
        },
        'extract_post_total': {'before': before, 'after': after},
    }, ensure_ascii=False, indent=2))
