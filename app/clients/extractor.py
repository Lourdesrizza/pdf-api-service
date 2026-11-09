"""HTTP client for the PDF extraction service."""

import httpx

from app.clients.base import UpstreamFailure, correlation_headers, map_transport_error, map_upstream_status
from app.clients.circuit import CircuitBreaker
from app.schemas import ExtractionResult


SERVICE = "extractor"


class ExtractorClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str, timeout: float = 30):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.url = f"{self.base_url}/extract"
        self.timeout = timeout
        self._circuit = CircuitBreaker(SERVICE)

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

    async def extract(self, pdf: bytes) -> tuple[str, int]:
        with self._circuit.operation():
            try:
                response = await self.http.post(
                    self.url,
                    content=pdf,
                    headers={"Content-Type": "application/pdf", **correlation_headers()},
                    timeout=self.timeout,
                )
            except httpx.RequestError as exc:
                raise map_transport_error(exc, SERVICE) from exc

            map_upstream_status(response, SERVICE, extractor=True)
            if response.status_code != 200:
                raise UpstreamFailure(
                    502, "invalid_upstream_response", "El extractor devolvió un estado inesperado."
                )
            try:
                result = ExtractionResult.model_validate(response.json())
            except (ValueError, TypeError) as exc:
                raise UpstreamFailure(
                    502,
                    "invalid_upstream_response",
                    "El extractor devolvió una respuesta inválida.",
                ) from exc
            return result.content, result.page_count
