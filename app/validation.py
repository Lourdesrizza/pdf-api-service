from fastapi import Request
from app.errors import APIError


async def read_limited_body(request: Request, max_bytes: int) -> bytes:
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
    from email.message import Message
    from email.parser import BytesParser
    from email import policy

    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    if not message.is_multipart():
        raise APIError(400, "invalid_multipart", "El formulario multipart no es válido.")
    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        if disposition == "form-data" and part.get_param("name", header="content-disposition") == "file":
            payload = part.get_payload(decode=True) or b""
            return payload, part.get_filename()
    raise APIError(400, "missing_file", "El formulario debe incluir el campo 'file'.")


async def receive_pdf(request: Request, max_bytes: int) -> tuple[bytes, str]:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in {"application/pdf", "multipart/form-data"}:
        raise APIError(415, "unsupported_media_type", "Use application/pdf o multipart/form-data.")
    body = await read_limited_body(request, max_bytes)
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
    filename = filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        filename = "document.pdf"
    return body, filename[:255]
