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
    logger.error("Request validation failed request_id=%s errors=%r", getattr(request.state, "request_id", "unknown"), exc.errors())
    return JSONResponse(status_code=422, content={"error": "validation_error", "detail": "La petición no cumple el formato esperado."})


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    logger.error("HTTP request failed request_id=%s status=%s detail=%s", getattr(request.state, "request_id", "unknown"), exc.status_code, exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "detail": str(exc.detail)}, headers=exc.headers)


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unexpected application failure request_id=%s", getattr(request.state, "request_id", "unknown"))
    return JSONResponse(status_code=500, content={"error": "internal_error", "detail": "Ocurrió un error interno."})


def install_handlers(app: FastAPI) -> None:
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
