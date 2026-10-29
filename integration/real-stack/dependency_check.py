import json
import os
import httpx

mode = os.environ['CHECK_MODE']
expected = {'extractor-down': {'extractor': 'unavailable', 'documents': 'ok'}, 'documents-down': {'extractor': 'ok', 'documents': 'unavailable'}}[mode]
with httpx.Client(timeout=15) as client:
    ready = client.get('http://api:8000/ready')
    if ready.status_code != 503 or ready.json().get('dependencies') != expected:
        raise RuntimeError(f'{mode} readiness mismatch: {ready.status_code} {ready.text}')
    response = client.post('http://api:8000/process', content=b'%PDF-1.4\nnot-persisted-integration-check\n', headers={'Content-Type': 'application/pdf', 'X-Filename': 'dependency-check.pdf'})
    if response.status_code != 502:
        raise RuntimeError(f'{mode} process expected sanitized HTTP 502, received {response.status_code}: {response.text}')
    body = response.json()
    if set(body) != {'error', 'detail'} or body.get('error') != 'upstream_unavailable':
        raise RuntimeError(f'{mode} error shape mismatch: {body}')
    print(json.dumps({'mode': mode, 'ready': {'status': ready.status_code, 'body': ready.json()}, 'process': {'status': response.status_code, 'body': body}}, ensure_ascii=False, indent=2))
