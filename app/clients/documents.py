"""HTTP client for the Documents service contract."""

import httpx

from app.clients.base import correlation_headers, map_transport_error, map_upstream_status
from app.errors import APIError
from app.schemas import DocumentCreation, DocumentPayload


class DocumentClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str, timeout: float = 5):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def health(self, timeout: float) -> bool:
        try:
            response = await self.http.get(
                f"{self.base_url}/health/ready",
                headers=correlation_headers(),
                timeout=timeout,
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def find_by_checksum(self, checksum: str) -> DocumentPayload | None:
        try:
            response = await self.http.get(
                f"{self.base_url}/documents/by-checksum/{checksum}",
                headers=correlation_headers(),
                timeout=self.timeout,
            )
        except httpx.TransportError as exc:
            raise map_transport_error(exc, "document service") from exc

        if response.status_code == 404:
            return None
        map_upstream_status(response, "document service")
        return self._parse(response, checksum)

    async def create(
        self,
        *,
        checksum: str,
        filename: str,
        content: str,
        page_count: int,
    ) -> DocumentCreation | None:
        body = {
            "checksum": checksum,
            "filename": filename,
            "content": content,
            "page_count": page_count,
        }
        try:
            response = await self.http.post(
                f"{self.base_url}/documents",
                json=body,
                headers=correlation_headers(),
                timeout=self.timeout,
            )
        except httpx.TransportError as exc:
            raise map_transport_error(exc, "document service") from exc

        if response.status_code == 409:
            return None
        if response.status_code not in (200, 201):
            map_upstream_status(response, "document service")
            raise APIError(
                502,
                "upstream_error",
                "El document service devolvió una respuesta inesperada.",
            )

        return DocumentCreation(
            document=self._parse(response, checksum),
            created=response.status_code == 201,
        )

    @staticmethod
    def _parse(response: httpx.Response, checksum: str) -> DocumentPayload:
        try:
            document = DocumentPayload.model_validate(response.json())
            if document.checksum.lower() != checksum.lower():
                raise ValueError("checksum mismatch")
            return document
        except (ValueError, TypeError) as exc:
            raise APIError(
                502,
                "invalid_upstream_response",
                "El document service devolvió una respuesta inválida.",
            ) from exc
