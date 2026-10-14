from app.checksum import calculate_checksum
from app.clients.documents import DocumentClient
from app.clients.extractor import ExtractorClient
from app.schemas import ProcessResponse


class Orchestrator:
    def __init__(self, documents: DocumentClient, extractor: ExtractorClient):
        self.documents = documents
        self.extractor = extractor

    async def process(self, pdf: bytes, filename: str) -> ProcessResponse:
        checksum = calculate_checksum(pdf)
        existing = await self.documents.find_by_checksum(checksum)
        if existing:
            return self._result(existing, checksum, "existing")
        content, page_count = await self.extractor.extract(pdf)
        created = await self.documents.create(checksum=checksum, filename=filename, content=content, page_count=page_count)
        if created is None:
            existing = await self.documents.find_by_checksum(checksum)
            if existing is None:
                from app.errors import APIError
                raise APIError(502, "invalid_upstream_response", "El documento duplicado no pudo recuperarse.")
            return self._result(existing, checksum, "existing")
        return self._result(created, checksum, "extracted")

    @staticmethod
    def _result(document, checksum: str, source: str) -> ProcessResponse:
        return ProcessResponse(
            document_id=str(document.id) if document.id is not None else checksum,
            checksum=document.checksum or checksum,
            content=document.resolved_content,
            page_count=document.page_count,
            source=source,
        )
