from fastapi import FastAPI, Request

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok", "service": "extractor-fake"}


@app.post("/extract")
async def extract(request: Request):
    pdf = await request.body()
    return {"content": f"Fake extraction ({len(pdf)} bytes)", "page_count": 1}
