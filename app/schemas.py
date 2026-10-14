from pydantic import BaseModel, ConfigDict, Field


class ProcessResponse(BaseModel):
    document_id: str
    checksum: str
    content: str
    page_count: int | None = None
    source: str = Field(pattern="^(existing|extracted)$")


class ErrorResponse(BaseModel):
    error: str
    detail: str
    dependencies: dict[str, str] | None = None


class DocumentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | int
    checksum: str
    filename: str = "document.pdf"
    content: str | None = None
    extracted_text: str | None = None
    page_count: int | None = None

    @property
    def resolved_content(self) -> str:
        return self.content if self.content is not None else (self.extracted_text or "")
