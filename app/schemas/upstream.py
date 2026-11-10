from pydantic import BaseModel, ConfigDict, Field


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
