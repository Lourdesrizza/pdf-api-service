"""Request correlation and unexpected HTTP errors."""

import uuid

from fastapi import Request

from app.clients.base import request_id_context
from app.errors import unexpected_error_handler


def _is_valid_request_id(value: str) -> bool:
    return bool(value) and len(value) <= 128 and value.isascii() and all(
        32 <= ord(character) < 127 for character in value
    )


async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "")
    if not _is_valid_request_id(request_id):
        request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    token = request_id_context.set(request_id)
    try:
        response = await call_next(request)
    except Exception as exc:
        response = await unexpected_error_handler(request, exc)
    finally:
        request_id_context.reset(token)
    response.headers["X-Request-ID"] = request_id
    return response
