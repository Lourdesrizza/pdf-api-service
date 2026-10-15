"""Document Service contract adapter. Confirm the pending fields with Angelina."""
import httpx

from app.clients.base import map_transport_error, map_upstream_status
from app.errors import APIError
from app.schemas import DocumentPayload


class DocumentClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str, timeout: float = 5):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def health(self, timeout: float) -> bool:
        try:
            response = await self.http.get(f"{self.base_url}/health", timeout=timeout)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def find_by_checksum(self, checksum: str) -> DocumentPayload | None:
        try:
            response = await self.http.get(f"{self.base_url}/documents/checksum/{checksum}", timeout=self.timeout)
        except httpx.TransportError as exc:
            raise map_transport_error(exc, "document service") from exc
        if response.status_code == 404:
            return None
        map_upstream_status(response, "document service")
        return self._parse(response)

    async def create(self, *, checksum: str, filename: str, content: str, page_count: int) -> DocumentPayload | None:
        # Compatibility adapter: Document Service currently names content `extracted_text`.
        body = {"checksum": checksum, "filename": filename, "extracted_text": content, "page_count": page_count}
        try:
            response = await self.http.post(f"{self.base_url}/documents", json=body, timeout=self.timeout)
        except httpx.TransportError as exc:
            raise map_transport_error(exc, "document service") from exc
        if response.status_code == 409:
            return None
        if response.status_code not in (200, 201):
            map_upstream_status(response, "document service")
            raise APIError(502, "upstream_error", "El document service devolvió una respuesta inesperada.")
        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> DocumentPayload:
        try:
            return DocumentPayload.model_validate(response.json())
        except (ValueError, TypeError):
            raise APIError(502, "invalid_upstream_response", "El document service devolvió una respuesta inválida.")
