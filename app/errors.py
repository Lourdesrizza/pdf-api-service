from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging

logger = logging.getLogger("pdf_api")


class APIError(Exception):
    def __init__(self, status_code: int, error: str, detail: str, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.error = error
        self.detail = detail
        self.headers = headers or {}


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    logger.error("Request failed request_id=%s status=%s code=%s detail=%s", getattr(request.state, "request_id", "unknown"), exc.status_code, exc.error, exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"error": exc.error, "detail": exc.detail}, headers=exc.headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.error("Request validation failed request_id=%s count=%s", getattr(request.state, "request_id", "unknown"), len(exc.errors()))
    return JSONResponse(status_code=422, content={"error": "validation_error", "detail": "La petición no cumple el formato esperado."})


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    logger.error("HTTP request failed request_id=%s status=%s detail=%s", getattr(request.state, "request_id", "unknown"), exc.status_code, exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "detail": str(exc.detail)}, headers=exc.headers)


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error("Unexpected application failure request_id=%s type=%s", request_id, type(exc).__name__)
    return JSONResponse(status_code=500, content={"error": "internal_error", "detail": "Ocurrió un error interno."}, headers={"X-Request-ID": request_id})


def install_handlers(app: FastAPI) -> None:
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
