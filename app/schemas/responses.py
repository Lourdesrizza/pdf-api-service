from typing import Literal

from pydantic import BaseModel, Field


class ProcessResponse(BaseModel):
    document_id: str
    checksum: str
    content: str
    page_count: int = Field(strict=True, gt=0)
    source: Literal["existing", "extracted"]


class ErrorResponse(BaseModel):
    error: str
    detail: str
    dependencies: dict[str, str] | None = None
