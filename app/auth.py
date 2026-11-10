"""Bearer authentication for API endpoints."""

from hmac import compare_digest

from fastapi import Request

from app.config import Settings
from app.errors import APIError


def _has_valid_bearer_token(request: Request, expected_token: str) -> bool:
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


def require_bearer_token(request: Request, expected_token: str) -> None:
    if not _has_valid_bearer_token(request, expected_token):
        raise APIError(
            401,
            "unauthorized",
            "Se requiere un token Bearer válido.",
            {"WWW-Authenticate": "Bearer"},
        )


def require_process_auth(request: Request, settings: Settings) -> None:
    if settings.api_require_auth:
        require_bearer_token(request, settings.api_access_token.get_secret_value())
