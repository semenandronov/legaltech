"""Worker FastAPI — обработка PDF/OCR без тяжёлого API prewarm.

Запуск (тот же Docker-образ, другая команда):
  uvicorn app.worker_app:app --host 0.0.0.0 --port ${PORT:-8000}

Env для worker:
  APP_ROLE=worker
  INTERNAL_WORKER_SECRET=<тот же секрет, что на API>
  RESET_STUCK_FILES_ON_STARTUP=false
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI

from app.config import config
from app.routes import health, internal_worker
from app.utils.database import init_db

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

logger.info("Worker: initializing database...")
init_db()

app = FastAPI(
    title=f"{config.API_TITLE} Worker",
    version=config.API_VERSION,
)
app.include_router(health.router, tags=["health"])
app.include_router(internal_worker.router)


@app.on_event("startup")
async def _worker_startup() -> None:
    """Лёгкий prewarm OCR-пайплайна без BM25 / case-assistant / checkpointer."""
    try:
        from app.services.document_processor import get_document_processor

        await asyncio.to_thread(get_document_processor)
        logger.info("Worker: document processor pre-warmed")
    except Exception as exc:
        logger.warning("Worker: document processor prewarm skipped: %s", exc)
