import hashlib
import json
import httpx

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
    if response.status_code != 200 or body.get('source') != 'existing' or body.get('checksum') != checksum or body.get('page_count') != 1 or 'ISOLATED PDF API EXTRACTION PROOF' not in body.get('content', ''):
        raise RuntimeError(f'persistence result mismatch: {response.status_code} {body}')
    metrics_after = client.get('http://extractor:8000/metrics')
    metrics_after.raise_for_status()
    after = sum(int(float(line.rsplit(None, 1)[-1])) for line in metrics_after.text.splitlines() if line.startswith('pdf_http_requests_total{') and 'method="POST"' in line and 'route="/extract"' in line)
    if after != before:
        raise RuntimeError(f'extractor counter changed after documents restart: {before} -> {after}')
    print(json.dumps({'ready': ready.json(), 'after_documents_restart': {'status': response.status_code, 'body': body}, 'extract_post_total': {'before': before, 'after': after}}, ensure_ascii=False, indent=2))
