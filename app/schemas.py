from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class DocumentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    id: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    content: str
    page_count: int = Field(strict=True, gt=0)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(strict=True)

    content: str
    page_count: int = Field(gt=0)


class DocumentCreation(BaseModel):
    document: DocumentPayload
    created: bool
