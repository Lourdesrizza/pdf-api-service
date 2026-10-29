import pytest

from app.main import app, lifespan


@pytest.mark.asyncio
async def test_lifespan_closes_shared_http_client():
    async with lifespan(app):
        client = app.state.documents.http
        assert app.state.extractor.http is client
        assert not client.is_closed
    assert client.is_closed
