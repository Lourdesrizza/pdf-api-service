from typing import Literal, Protocol

from app.checksum import calculate_checksum
from app.errors import APIError
from app.schemas import DocumentCreation, DocumentPayload, ProcessResponse


class DocumentsGateway(Protocol):
    async def find_by_checksum(self, checksum: str) -> DocumentPayload | None: ...

    async def create(
        self, *, checksum: str, filename: str, content: str, page_count: int
    ) -> DocumentCreation | None: ...


class ExtractorGateway(Protocol):
    async def extract(self, pdf: bytes) -> tuple[str, int]: ...


ProcessSource = Literal["existing", "extracted"]


class Orchestrator:
    def __init__(self, documents: DocumentsGateway, extractor: ExtractorGateway):
        self.documents = documents
        self.extractor = extractor

    async def process(self, pdf: bytes, filename: str) -> ProcessResponse:
        checksum = calculate_checksum(pdf)
        existing = await self.documents.find_by_checksum(checksum)
        if existing is not None:
            return self._result(existing, "existing")

        content, page_count = await self.extractor.extract(pdf)
        creation = await self.documents.create(
            checksum=checksum,
            filename=filename,
            content=content,
            page_count=page_count,
        )
        if creation is None:
            existing = await self.documents.find_by_checksum(checksum)
            if existing is None:
                raise APIError(
                    502,
                    "invalid_upstream_response",
                    "El documento duplicado no pudo recuperarse.",
                )
            return self._result(existing, "existing")

        source: ProcessSource = "extracted" if creation.created else "existing"
        return self._result(creation.document, source)

    @staticmethod
    def _result(document: DocumentPayload, source: ProcessSource) -> ProcessResponse:
        return ProcessResponse(
            document_id=document.id,
            checksum=document.checksum,
            content=document.content,
            page_count=document.page_count,
            source=source,
        )
