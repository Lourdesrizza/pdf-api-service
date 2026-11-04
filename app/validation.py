import asyncio
from email import policy
from email.parser import BytesParser

from fastapi import Request

from app.errors import APIError


async def read_limited_body(request: Request, max_bytes: int) -> bytes:
    lengths = request.headers.getlist("content-length")
    if lengths:
        value = lengths[0]
        if len(lengths) != 1 or not value.isascii() or not value.isdecimal():
            raise APIError(400, "invalid_content_length", "Content-Length no es válido.")
        # Compare decimal strings before converting an arbitrarily long header.
        normalized = value.lstrip("0") or "0"
        maximum = str(max_bytes)
        if len(normalized) > len(maximum) or (len(normalized) == len(maximum) and normalized > maximum):
            raise APIError(413, "file_too_large", "El archivo supera el tamaño máximo permitido.")
    body = bytearray()
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise APIError(413, "file_too_large", "El archivo supera el tamaño máximo permitido.")
        body.extend(chunk)
    return bytes(body)


def parse_multipart(body: bytes, content_type: str) -> tuple[bytes, str | None]:
    """Extract the `file` part from an already size-limited multipart body."""
    if "\r" in content_type or "\n" in content_type:
        raise APIError(400, "invalid_multipart", "El formulario multipart no es válido.")
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    if (
        not message.is_multipart()
        or not message.get_boundary()
        or any(part.defects for part in message.walk())
        or message.preamble not in (None, "")
        or (message.epilogue or "").strip()
    ):
        raise APIError(400, "invalid_multipart", "El formulario multipart no es válido.")
    parts = list(message.iter_parts())
    if not parts:
        raise APIError(400, "missing_file", "El formulario debe incluir el campo 'file'.")
    if len(parts) != 1:
        raise APIError(400, "invalid_multipart", "El formulario debe incluir una única parte file.")
    part = parts[0]
    if part.is_multipart() or part.get("Content-Transfer-Encoding") is not None:
        raise APIError(400, "invalid_multipart", "La estructura multipart no está admitida.")
    if (
        len(part.get_all("Content-Disposition", [])) != 1
        or part.get_content_disposition() != "form-data"
        or part.get_param("name", header="content-disposition") != "file"
    ):
        raise APIError(400, "missing_file", "El formulario debe incluir el campo 'file'.")
    return part.get_payload(decode=True) or b"", part.get_filename()


async def receive_pdf(request: Request, max_bytes: int, timeout_seconds: float = 30) -> tuple[bytes, str]:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in {"application/pdf", "multipart/form-data"}:
        raise APIError(415, "unsupported_media_type", "Use application/pdf o multipart/form-data.")
    try:
        async with asyncio.timeout(timeout_seconds):
            body = await read_limited_body(request, max_bytes)
    except TimeoutError as exc:
        raise APIError(408, "body_timeout", "Se agotó el tiempo para recibir el cuerpo.") from exc
    filename = request.headers.get("x-filename")
    if media_type == "multipart/form-data":
        body, multipart_name = parse_multipart(body, request.headers.get("content-type", ""))
        filename = multipart_name or filename
    if not body:
        raise APIError(400, "empty_pdf", "El PDF está vacío.")
    if len(body) > max_bytes:
        raise APIError(413, "file_too_large", "El archivo supera el tamaño máximo permitido.")
    if not body.startswith(b"%PDF-"):
        raise APIError(400, "invalid_pdf", "El archivo no tiene una firma PDF válida.")
    filename = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    filename = "".join(char for char in filename if char.isprintable()).strip()
    if not filename.lower().endswith(".pdf"):
        filename = "document.pdf"
    return body, filename[:255].strip() or "document.pdf"
