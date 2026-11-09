import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.main import app, lifespan


def test_process_auth_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("API_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("API_ACCESS_TOKEN", raising=False)
    settings = Settings(_env_file=None)
    assert settings.api_require_auth is False
    assert settings.api_access_token.get_secret_value() == ""


@pytest.mark.parametrize("token", [None, "", "fake invalid access token with spaces", "fake-too-short"])
def test_restricted_app_rejects_invalid_token_on_startup(monkeypatch, tmp_path, token):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("API_REQUIRE_AUTH", "true")
    if token is None:
        monkeypatch.delenv("API_ACCESS_TOKEN", raising=False)
    else:
        monkeypatch.setenv("API_ACCESS_TOKEN", token)

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "API_ACCESS_TOKEN" in result.stderr
    if token:
        assert token not in result.stdout + result.stderr


@pytest.mark.asyncio
async def test_lifespan_closes_shared_http_client():
    async with lifespan(app):
        client = app.state.documents.http
        assert app.state.extractor.http is client
        assert not client.is_closed
    assert client.is_closed
