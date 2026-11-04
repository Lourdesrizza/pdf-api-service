"""Runs inside the exclusive client: brief new/repeated load or slow upload."""
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx


async def main():
    pdf = Path('/fixtures/proof.pdf').read_bytes()
    async with httpx.AsyncClient(timeout=90) as client:
        if sys.argv[1] == 'shutdown':
            async def body():
                yield pdf[:100]
                # Host waits for this marker before delivering SIGTERM.
                await asyncio.sleep(.5)
                print('INFLIGHT', flush=True)
                await asyncio.sleep(3)
                yield pdf[100:]
            response = await client.post('http://api:8000/process', content=body(),
                                         headers={'Content-Type': 'application/pdf'})
            assert response.status_code == 200
            assert response.json()['source'] == 'existing'
            print(json.dumps({'status': response.status_code, 'source': 'existing'}), flush=True)
            return
        async def submit(data):
            start = time.perf_counter()
            response = await client.post('http://api:8000/process', content=data,
                                         headers={'Content-Type': 'application/pdf'})
            elapsed = (time.perf_counter() - start) * 1000
            result = response.json()
            if response.status_code == 200:
                assert result['checksum'] == hashlib.sha256(data).hexdigest()
            else:
                assert response.status_code == 503, response.status_code
            return {'ms': round(elapsed, 2), 'source': result.get('source'), 'status': response.status_code,
                    'error': result.get('error'), 'retry_after': response.headers.get('Retry-After')}
        # PDF comments after EOF change checksum without changing document pages.
        new = await asyncio.gather(*(submit(pdf + f'\n% audit-new-{time.time_ns()}-{i}\n'.encode()) for i in range(2)))
        assert any(item['source'] == 'extracted' for item in new)
        repeated = []
        deadline = time.perf_counter() + 5
        while time.perf_counter() < deadline:
            repeated.extend(await asyncio.gather(submit(pdf), submit(pdf)))
        latencies = sorted(item['ms'] for item in repeated)
        assert all(item['source'] == 'existing' for item in repeated)
        # Actual current Documents handles BSON documents above MongoDB's limit.
        too_large = await client.post('http://documents:8000/documents', json={
            'checksum': 'f' * 64, 'filename': 'oversized.pdf',
            'content': 'x' * (17 * 1024 * 1024), 'page_count': 1})
        assert too_large.status_code == 413, too_large.status_code
        print(json.dumps({'concurrency': 2, 'pdf_bytes': len(pdf), 'new': new,
                          'documents_oversized_status': too_large.status_code,
                          'repeated': {'requests': len(repeated), 'errors': 0,
                          'sources': sorted(set(item['source'] for item in repeated)),
                          'p50_ms': latencies[len(latencies)//2],
                          'p95_ms': latencies[int((len(latencies)-1)*.95)]}}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
