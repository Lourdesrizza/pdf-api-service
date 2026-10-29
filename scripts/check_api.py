"""Dedicated-environment E2E and conservative repeated-PDF load."""
import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

import httpx


class ContractError(RuntimeError):
    """The API response does not satisfy the public process contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_response(response: httpx.Response, checksum: str) -> dict:
    require(response.status_code == 200, f"Expected HTTP 200, received {response.status_code}")
    try:
        document = response.json()
    except ValueError as exc:
        raise ContractError("API response is not valid JSON") from exc
    require(isinstance(document, dict), "API response must be a JSON object")
    require(isinstance(document.get("document_id"), str) and bool(document["document_id"]), "document_id must be a non-empty string")
    require(document.get("checksum") == checksum, "API response checksum does not match the submitted PDF")
    require(isinstance(document.get("content"), str), "content must be a string")
    require(type(document.get("page_count")) is int and document["page_count"] > 0, "page_count must be a positive integer")
    require(document.get("source") in ("existing", "extracted"), "source must be existing or extracted")
    return document


async def run(args):
    pdf = Path(args.pdf).read_bytes()
    checksum = hashlib.sha256(pdf).hexdigest()
    async with httpx.AsyncClient(timeout=60) as client:
        async def send():
            response = await client.post(args.url, content=pdf, headers={"Content-Type": "application/pdf"})
            return validate_response(response, checksum)

        if args.mode == "e2e":
            first = await send()
            require(first["source"] == "extracted", "Use an unused PDF in a dedicated environment")
            second = await send()
            require(second["source"] == "existing", "The repeated PDF must be returned as existing")
            require(first["document_id"] == second["document_id"], "Repeated PDF returned a different document ID")
            require(first["checksum"] == second["checksum"], "Repeated PDF returned a different checksum")
            print(json.dumps({"first": first, "second": second}))
            print("No-extraction proof requires separate instrumentation.")
            return

        samples = []
        errors = 0
        sources = {"existing": 0, "extracted": 0}
        start = time.monotonic()
        deadline = start + args.duration

        async def worker():
            nonlocal errors
            while time.monotonic() < deadline:
                request_started = time.monotonic()
                try:
                    document = await send()
                    sources[document["source"]] += 1
                except (httpx.HTTPError, ValueError, ContractError):
                    errors += 1
                samples.append(time.monotonic() - request_started)
                await asyncio.sleep(0.1)

        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        elapsed = time.monotonic() - start
        ordered = sorted(samples)
        print(json.dumps({
            "requests": len(samples),
            "errors": errors,
            "elapsed_seconds": elapsed,
            "requests_per_second": len(samples) / elapsed,
            "p50_seconds": ordered[int((len(ordered) - 1) * 0.5)] if ordered else None,
            "p95_seconds": ordered[int((len(ordered) - 1) * 0.95)] if ordered else None,
            "sources": sources,
            "scenario": "same PDF, mostly deduplicated; not new-PDF extraction throughput",
        }))
        if errors:
            raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["e2e", "load"])
    parser.add_argument("--url", required=True)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--dedicated-test-environment", action="store_true", required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--duration", type=int, default=5)
    arguments = parser.parse_args()
    if not 1 <= arguments.concurrency <= 4 or not 1 <= arguments.duration <= 30:
        parser.error("concurrency 1..4; duration 1..30")
    asyncio.run(run(arguments))
