"""Bearer authentication for the processing endpoint."""

from hmac import compare_digest

from fastapi import Request

from app.config import Settings
from app.errors import APIError


def _has_valid_process_token(request: Request, expected_token: str) -> bool:
    authorization = request.headers.getlist("authorization")
    if len(authorization) != 1:
        return False
    scheme, _, token = authorization[0].partition(" ")
    token = token.lstrip(" ")
    return (
        scheme.lower() == "bearer"
        and token.isascii()
        and compare_digest(expected_token, token)
    )


def require_process_auth(request: Request, settings: Settings) -> None:
    if settings.api_require_auth and not _has_valid_process_token(
        request, settings.api_access_token.get_secret_value(),
    ):
        raise APIError(
            401,
            "unauthorized",
            "Se requiere un token Bearer válido.",
            {"WWW-Authenticate": "Bearer"},
        )
