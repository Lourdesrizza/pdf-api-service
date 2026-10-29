from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI()
records: dict[str, dict] = {}
lock = Lock()

class CreateDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checksum: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    filename: str | None = None
    content: str
    page_count: int = Field(strict=True, gt=0)

@app.get("/health")
@app.get("/health/ready")
def health():
    return {"status": "ok", "service": "documents-fake"}

@app.get("/documents/by-checksum/{checksum}")
def find(checksum: str):
    with lock:
        if checksum.lower() not in records:
            raise HTTPException(404, "not found")
        return records[checksum.lower()]

@app.post("/documents", status_code=201)
def create(item: CreateDocument, response: Response):
    checksum = item.checksum.lower()
    with lock:
        if checksum in records:
            response.status_code = 200
            return records[checksum]
        record = {**item.model_dump(), "checksum": checksum, "id": str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat()}
        records[checksum] = record
        return record
