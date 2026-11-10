import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.clients import base, circuit
from app.clients.documents import DocumentClient
from app.clients.extractor import ExtractorClient
from app.errors import APIError


CHECKSUM = "a" * 64
DOCUMENT = {"id": "doc-1", "checksum": CHECKSUM, "content": "text", "page_count": 1}


@pytest.fixture
def clock(monkeypatch):
    now = 0.0

    def advance(seconds):
        nonlocal now
        now += seconds

    monkeypatch.setattr(circuit, "monotonic", lambda: now)
    return advance


@pytest.fixture
def retry_sleep(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(base, "sleep", sleep)
    return sleep


@pytest.mark.parametrize("down", ["documents", "extractor"])
async def test_circuits_are_independent_and_documents_save_is_not_retried(down, clock, retry_sleep):
    calls = []

    def respond(request):
        service = request.url.host
        calls.append((service, request.method, request.url.path))
        if request.url.path == "/health/ready":
            return httpx.Response(200)
        if service == down:
            return httpx.Response(500)
        if service == "documents":
            return httpx.Response(201, json=DOCUMENT)
        return httpx.Response(200, json={"content": "text", "page_count": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        documents = DocumentClient(http, "http://documents")
        extractor = ExtractorClient(http, "http://extractor")

        async def save():
            return await documents.create(
                checksum=CHECKSUM, filename="test.pdf", content="text", page_count=1,
            )

        async def extract():
            return await extractor.extract(b"%PDF-")

        broken, healthy = (save, extract) if down == "documents" else (extract, save)
        attempts = 1 if down == "documents" else 3
        for count in range(1, 4):
            with pytest.raises(APIError) as failed:
                await broken()
            assert failed.value.status_code == 502
            assert len(calls) == count * attempts
            assert calls[-1][:2] == (down, "POST")

        for _ in range(2):
            with pytest.raises(APIError) as rejected:
                await broken()
            assert rejected.value.status_code == 503
            assert rejected.value.error == "upstream_unavailable"
            assert rejected.value.headers == {"Retry-After": "10"}
        if down == "documents":
            with pytest.raises(APIError) as rejected_lookup:
                await documents.find_by_checksum(CHECKSUM)
            assert rejected_lookup.value.status_code == 503
        assert len(calls) == 3 * attempts

        assert await healthy()
        assert calls[-1][0] != down
        assert await (documents if down == "documents" else extractor).health(2)
        assert calls[-1] == (down, "GET", "/health/ready")
        with pytest.raises(APIError) as still_open:
            await broken()
        assert still_open.value.status_code == 503
        assert len(calls) == 3 * attempts + 2


async def test_lookup_counts_final_failure_once_and_probe_can_fail_or_recover(clock, retry_sleep):
    status = 503
    calls = 0

    def respond(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        documents = DocumentClient(http, "http://documents")
        for count in (3, 6, 9):
            with pytest.raises(APIError) as failed:
                await documents.find_by_checksum(CHECKSUM)
            assert failed.value.headers == {"Retry-After": "1"}
            assert calls == count
        assert retry_sleep.await_count == 6

        clock(9)
        with pytest.raises(APIError) as rejected:
            await documents.find_by_checksum(CHECKSUM)
        assert rejected.value.headers == {"Retry-After": "1"}
        assert calls == 9

        clock(1)
        with pytest.raises(APIError) as failed_probe:
            await documents.find_by_checksum(CHECKSUM)
        assert failed_probe.value.headers == {"Retry-After": "1"}
        assert calls == 10
        assert retry_sleep.await_count == 6

        with pytest.raises(APIError) as reopened:
            await documents.find_by_checksum(CHECKSUM)
        assert reopened.value.headers == {"Retry-After": "10"}
        assert calls == 10

        clock(10)
        status = 404
        assert await documents.find_by_checksum(CHECKSUM) is None
        assert await documents.find_by_checksum(CHECKSUM) is None
        assert calls == 12


async def test_only_one_probe_and_cancelled_probe_releases_slot(clock):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def respond(request):
        nonlocal calls
        calls += 1
        if calls <= 3:
            return httpx.Response(503, headers={"Retry-After": "1"})
        if calls == 4:
            entered.set()
            await release.wait()
        if calls == 5:
            return httpx.Response(502)
        return httpx.Response(200, json={"content": "text", "page_count": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        extractor = ExtractorClient(http, "http://extractor")
        for _ in range(3):
            with pytest.raises(APIError):
                await extractor.extract(b"%PDF-")

        clock(10)
        probe = asyncio.create_task(extractor.extract(b"%PDF-"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            with pytest.raises(APIError) as rejected:
                await extractor.extract(b"%PDF-")
            assert rejected.value.status_code == 503
            assert calls == 4
        finally:
            probe.cancel()
            with pytest.raises(asyncio.CancelledError):
                await probe

        with pytest.raises(APIError) as reopened:
            await extractor.extract(b"%PDF-")
        assert reopened.value.headers == {"Retry-After": "10"}
        assert calls == 4
        clock(10)
        with pytest.raises(APIError) as failed_probe:
            await extractor.extract(b"%PDF-")
        assert failed_probe.value.status_code == 502
        assert calls == 5

        clock(10)
        assert await extractor.extract(b"%PDF-") == ("text", 1)
        assert await extractor.extract(b"%PDF-") == ("text", 1)
        assert calls == 7


async def test_late_success_from_before_opening_does_not_close_circuit(clock):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def respond(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"content": "text", "page_count": 1})
        return httpx.Response(502, headers={"Retry-After": "1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        extractor = ExtractorClient(http, "http://extractor")
        pending = asyncio.create_task(extractor.extract(b"%PDF-"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            for _ in range(3):
                with pytest.raises(APIError) as failed:
                    await extractor.extract(b"%PDF-")
                assert failed.value.status_code == 502
        finally:
            release.set()
            assert await pending == ("text", 1)

        with pytest.raises(APIError) as rejected:
            await extractor.extract(b"%PDF-")
        assert rejected.value.status_code == 503
        assert calls == 4


@pytest.mark.parametrize("first", [502, httpx.ReadTimeout, httpx.RemoteProtocolError])
async def test_successful_lookup_retry_keeps_headers_and_does_not_trip_circuit(first, retry_sleep):
    token = "fake-documents-token"
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) % 2:
            if isinstance(first, int):
                return httpx.Response(first)
            raise first("transient")
        return httpx.Response(200, json=DOCUMENT)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        documents = DocumentClient(http, "http://documents", api_token=SecretStr(token))
        for _ in range(4):
            result = await documents.find_by_checksum(CHECKSUM)
            assert result.id == DOCUMENT["id"]

    assert len(calls) == 8
    assert retry_sleep.await_count == 4
    retry_sleep.assert_awaited_with(0.05)
    assert all(request.headers["Authorization"] == f"Bearer {token}" for request in calls)
    assert calls[0].headers["X-Request-ID"] == calls[1].headers["X-Request-ID"]


@pytest.mark.parametrize(
    ("status", "headers", "mapped"),
    [(401, {}, 502), (403, {}, 502), (404, {}, None), (429, {}, 503), (503, {"Retry-After": "7"}, 503)],
)
async def test_lookup_does_not_retry_noneligible_responses(status, headers, mapped, retry_sleep):
    respond = AsyncMock(return_value=httpx.Response(status, headers=headers))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        documents = DocumentClient(http, "http://documents")
        if mapped is None:
            assert await documents.find_by_checksum(CHECKSUM) is None
        else:
            with pytest.raises(APIError) as failed:
                await documents.find_by_checksum(CHECKSUM)
            assert failed.value.status_code == mapped
            if headers:
                assert failed.value.headers == headers
    respond.assert_awaited_once()
    retry_sleep.assert_not_awaited()


async def test_lookup_deadline_includes_attempts_and_pause(monkeypatch):
    loop = asyncio.get_running_loop()
    now = loop.time()
    calls = 0

    async def pause(delay):
        nonlocal now
        now += delay

    async def respond(request):
        nonlocal now, calls
        calls += 1
        if calls == 1:
            now += 0.6
            return httpx.Response(500)
        now += 0.36
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return httpx.Response(200, json=DOCUMENT)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        documents = DocumentClient(http, "http://documents", timeout=1)
        with monkeypatch.context() as patch:
            patch.setattr(loop, "time", lambda: now)
            patch.setattr(base, "sleep", pause)
            with pytest.raises(APIError) as failed:
                await documents.find_by_checksum(CHECKSUM)

    assert failed.value.status_code == 504
    assert calls == 2


@pytest.mark.parametrize("service", ["documents", "extractor"])
@pytest.mark.parametrize("recovers", [True, False])
async def test_backoff_recovers_or_stops_after_three_attempts(service, recovers, retry_sleep):
    result = DOCUMENT if service == "documents" else {"content": "text", "page_count": 1}
    respond = AsyncMock(side_effect=[
        httpx.ConnectError("transient"),
        httpx.Response(502),
        httpx.Response(200, json=result) if recovers else httpx.Response(503),
    ])

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        if service == "documents":
            async def operation():
                return (await DocumentClient(http, "http://documents").find_by_checksum(CHECKSUM)).id
            expected = DOCUMENT["id"]
        else:
            async def operation():
                return await ExtractorClient(http, "http://extractor").extract(b"%PDF-")
            expected = ("text", 1)

        if recovers:
            assert await operation() == expected
        else:
            with pytest.raises(APIError) as failed:
                await operation()
            assert failed.value.status_code == 503
            assert failed.value.headers == {"Retry-After": "1"}

    assert respond.await_count == 3
    assert [call.args[0] for call in retry_sleep.await_args_list] == [0.05, 0.10]


async def test_save_does_not_replay_after_losing_response(retry_sleep):
    respond = AsyncMock(side_effect=[httpx.ReadError("response lost"), httpx.Response(200, json=DOCUMENT)])

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        documents = DocumentClient(http, "http://documents")
        with pytest.raises(APIError) as failed:
            await documents.create(
                checksum=CHECKSUM, filename="test.pdf", content="text", page_count=1,
            )
        assert failed.value.status_code == 502
        assert (await documents.find_by_checksum(CHECKSUM)).id == DOCUMENT["id"]

    assert [call.args[0].method for call in respond.await_args_list] == ["POST", "GET"]
    retry_sleep.assert_not_awaited()
