import httpx
import logging
from contextvars import ContextVar

from app.errors import APIError

logger = logging.getLogger("pdf_api")
request_id_context: ContextVar[str] = ContextVar("request_id", default="unknown")


def map_transport_error(exc: Exception, service: str) -> APIError:
    logger.exception("Upstream transport failure request_id=%s service=%s", request_id_context.get(), service)
    if isinstance(exc, httpx.TimeoutException):
        return APIError(504, "upstream_timeout", f"Se agotó el tiempo de espera del servicio {service}.")
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, httpx.ProtocolError)):
        return APIError(503, "upstream_unavailable", f"El servicio {service} no está disponible.")
    return APIError(502, "upstream_error", f"No se pudo procesar la respuesta del servicio {service}.")


def map_upstream_status(response: httpx.Response, service: str, *, extractor: bool = False) -> None:
    if response.status_code >= 400:
        logger.error("Upstream response request_id=%s service=%s status=%s body=%s", request_id_context.get(), service, response.status_code, response.text[:1000])
    if extractor and response.status_code == 400:
        try:
            detail = response.json().get("detail", "El extractor rechazó el PDF.")
        except (ValueError, AttributeError):
            detail = "El extractor rechazó el PDF."
        raise APIError(422, "pdf_rejected", str(detail))
    if response.status_code in (429, 503):
        raise APIError(
            503,
            "upstream_unavailable",
            f"El servicio {service} está saturado o no disponible.",
            headers={"Retry-After": "1"},
        )
    if response.status_code >= 500:
        raise APIError(502, "upstream_error", f"El servicio {service} devolvió un error.")
    if response.status_code >= 400:
        raise APIError(502, "upstream_error", f"El servicio {service} devolvió una respuesta inesperada.")
