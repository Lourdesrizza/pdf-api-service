"""HTTP client for the Documents service contract."""

import httpx
from pydantic import SecretStr

from app.clients.base import (
    UpstreamFailure,
    correlation_headers,
    map_transport_error,
    map_upstream_status,
    request_with_backoff,
)
from app.clients.circuit import CircuitBreaker
from app.schemas.upstream import DocumentCreation, DocumentPayload


SERVICE = "document service"


class DocumentClient:
    def __init__(
        self, http: httpx.AsyncClient, base_url: str, timeout: float = 5,
        *, api_token: SecretStr | None = None,
    ):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._api_token = api_token
        self._circuit = CircuitBreaker(SERVICE)

    def _document_headers(self) -> dict[str, str]:
        headers = correlation_headers()
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token.get_secret_value()}"
        return headers

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
        with self._circuit.operation() as probe:
            response = await self._get_checksum(checksum, allow_retry=not probe)
            if response.status_code == 404:
                return None
            map_upstream_status(response, SERVICE)
            if response.status_code != 200:
                raise UpstreamFailure(
                    502, "invalid_upstream_response", "El document service devolvió un estado inesperado."
                )
            return self._parse(response, checksum)

    async def _get_checksum(self, checksum: str, *, allow_retry: bool) -> httpx.Response:
        try:
            return await request_with_backoff(
                self.http,
                "GET",
                f"{self.base_url}/documents/by-checksum/{checksum}",
                headers=self._document_headers(),
                timeout_seconds=self.timeout,
                allow_retry=allow_retry,
            )
        except (httpx.RequestError, TimeoutError) as exc:
            raise map_transport_error(exc, SERVICE) from exc

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
        with self._circuit.operation():
            # A lost response can hide a successful write and change the observed 201 to 200.
            try:
                response = await self.http.post(
                    f"{self.base_url}/documents",
                    json=body,
                    headers=self._document_headers(),
                    timeout=self.timeout,
                )
            except httpx.RequestError as exc:
                raise map_transport_error(exc, SERVICE) from exc

            if response.status_code == 409:
                return None
            if response.status_code not in (200, 201):
                map_upstream_status(response, SERVICE)
                raise UpstreamFailure(
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
            raise UpstreamFailure(
                502,
                "invalid_upstream_response",
                "El document service devolvió una respuesta inválida.",
            ) from exc
