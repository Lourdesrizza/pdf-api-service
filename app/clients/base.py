import logging
from contextvars import ContextVar

import httpx

from app.errors import APIError

logger = logging.getLogger("pdf_api")
request_id_context: ContextVar[str] = ContextVar("request_id", default="unknown")


def correlation_headers() -> dict[str, str]:
    return {"X-Request-ID": request_id_context.get()}


def map_transport_error(exc: httpx.TransportError, service: str) -> APIError:
    logger.error(
        "Upstream transport failure service=%s type=%s request_id=%s",
        service,
        type(exc).__name__,
        request_id_context.get(),
    )
    if isinstance(exc, httpx.TimeoutException):
        return APIError(
            504,
            "upstream_timeout",
            f"Se agotó el tiempo de espera del servicio {service}.",
        )
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, httpx.ProtocolError)):
        return APIError(
            502,
            "upstream_unavailable",
            f"El servicio {service} no está disponible.",
        )
    return APIError(
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
        raise APIError(
            503,
            "upstream_unavailable",
            f"El servicio {service} está saturado o no disponible.",
            headers={"Retry-After": _retry_after(response)},
        )
    if response.status_code >= 500:
        raise APIError(502, "upstream_error", f"El servicio {service} devolvió un error.")
    if response.status_code >= 400:
        raise APIError(
            502,
            "upstream_error",
            f"El servicio {service} devolvió una respuesta inesperada.",
        )
