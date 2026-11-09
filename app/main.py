"""Application composition and Uvicorn entry point."""

import logging
import sys

from fastapi import FastAPI

from app.config import get_settings
from app.errors import install_handlers
from app.lifecycle import lifespan
from app.middleware import request_context
from app.routes import router

settings = get_settings()
logging.basicConfig(
    stream=sys.stdout,
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="PDF API Service", version="0.1.0", lifespan=lifespan)
app.state.settings = settings
install_handlers(app)
app.middleware("http")(request_context)
app.include_router(router)
