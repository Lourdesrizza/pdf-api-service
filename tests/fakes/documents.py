from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()
records: dict[str, dict] = {}


class CreateDocument(BaseModel):
    checksum: str
    filename: str
    content: str
    page_count: int | None = None


@app.get("/health")
@app.get("/health/ready")
def health():
    return {"status": "ok", "service": "documents-fake"}


@app.get("/documents/by-checksum/{checksum}")
def find(checksum: str):
    if checksum not in records:
        raise HTTPException(404, "not found")
    return records[checksum]


@app.post("/documents", status_code=201)
def create(item: CreateDocument):
    if item.checksum in records:
        raise HTTPException(409, "duplicate")
    record = {"id": item.checksum[:12], **item.model_dump()}
    records[item.checksum] = record
    return record
