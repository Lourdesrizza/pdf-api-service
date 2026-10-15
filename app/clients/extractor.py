import httpx

from app.clients.base import map_transport_error, map_upstream_status
from app.errors import APIError


class ExtractorClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str, timeout: float = 30):
        self.http = http
        self.url = f"{base_url.rstrip('/')}/extract"
        self.timeout = timeout

    async def health(self, timeout: float) -> bool:
        try:
            response = await self.http.get(self.url.rsplit("/", 1)[0] + "/health", timeout=timeout)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def extract(self, pdf: bytes) -> tuple[str, int]:
        try:
            response = await self.http.post(self.url, content=pdf, headers={"Content-Type": "application/pdf"}, timeout=self.timeout)
        except httpx.TransportError as exc:
            raise map_transport_error(exc, "extractor") from exc
        map_upstream_status(response, "extractor", extractor=True)
        try:
            payload = response.json()
            content = payload["content"]
            count = payload["page_count"]
            if not isinstance(content, str) or not isinstance(count, int) or count < 0:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise APIError(502, "invalid_upstream_response", "El extractor devolvió una respuesta inválida.")
        return content, count
