import logging
from asyncio import sleep, timeout
from contextvars import ContextVar
from typing import Literal

import httpx

from app.errors import APIError

logger = logging.getLogger("pdf_api")
request_id_context: ContextVar[str] = ContextVar("request_id", default="unknown")
RETRY_INITIAL_DELAY_SECONDS = 0.05
RETRY_MAX_ATTEMPTS = 3
TRANSIENT_STATUSES = {500, 502, 503, 504}
CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)
LOOKUP_RETRY_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)


class UpstreamFailure(APIError):
    """A failed operation that contributes to opening the dependency circuit."""


def correlation_headers() -> dict[str, str]:
    return {"X-Request-ID": request_id_context.get()}


async def request_with_backoff(
    http: httpx.AsyncClient,
    method: Literal["GET", "POST"],
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    allow_retry: bool,
    content: bytes | None = None,
) -> httpx.Response:
    """Send a repeatable operation within one deadline, including backoff."""
    max_attempts = RETRY_MAX_ATTEMPTS if allow_retry else 1
    retry_errors = LOOKUP_RETRY_ERRORS if method == "GET" else CONNECT_ERRORS
    retry_statuses = TRANSIENT_STATUSES | {408} if method == "GET" else TRANSIENT_STATUSES

    async with timeout(timeout_seconds):
        for attempt in range(max_attempts - 1):
            try:
                response = await http.request(
                    method, url, headers=headers, timeout=timeout_seconds, content=content
                )
            except retry_errors:
                pass
            else:
                if response.status_code not in retry_statuses or "Retry-After" in response.headers:
                    return response
            await sleep(RETRY_INITIAL_DELAY_SECONDS * 2**attempt)
        return await http.request(
            method, url, headers=headers, timeout=timeout_seconds, content=content
        )


def map_transport_error(exc: httpx.RequestError | TimeoutError, service: str) -> UpstreamFailure:
    logger.error(
        "Upstream transport failure service=%s type=%s request_id=%s",
        service,
        type(exc).__name__,
        request_id_context.get(),
    )
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return UpstreamFailure(
            504,
            "upstream_timeout",
            f"Se agotó el tiempo de espera del servicio {service}.",
        )
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, httpx.ProtocolError)):
        return UpstreamFailure(
            502,
            "upstream_unavailable",
            f"El servicio {service} no está disponible.",
        )
    return UpstreamFailure(
        502,
        "upstream_error",
        f"No se pudo procesar la respuesta del servicio {service}.",
    )


def _retry_after(response: httpx.Response) -> str:
    value = response.headers.get("Retry-After", "")
    if not value.isascii() or not value.isdecimal() or len(value) > 5:
        return "1"
    seconds = int(value)
    return str(seconds) if 1 <= seconds <= 86400 else "1"


def map_upstream_status(response: httpx.Response, service: str, *, extractor: bool = False) -> None:
    if response.status_code >= 400:
        logger.error(
            "Upstream response service=%s status=%s request_id=%s",
            service,
            response.status_code,
            request_id_context.get(),
        )

    if extractor and response.status_code in (400, 415):
        raise APIError(422, "pdf_rejected", "El extractor rechazó el PDF.")
    if extractor and response.status_code == 413:
        raise APIError(413, "file_too_large", "El PDF supera el límite del extractor.")
    if response.status_code in (429, 503):
        raise UpstreamFailure(
            503,
            "upstream_unavailable",
            f"El servicio {service} está saturado o no disponible.",
            headers={"Retry-After": _retry_after(response)},
        )
    if response.status_code >= 500:
        raise UpstreamFailure(502, "upstream_error", f"El servicio {service} devolvió un error.")
    if response.status_code >= 400:
        error_type = UpstreamFailure if response.status_code == 408 else APIError
        raise error_type(
            502,
            "upstream_error",
            f"El servicio {service} devolvió una respuesta inesperada.",
        )
