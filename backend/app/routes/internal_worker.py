"""Внутренний API worker-контейнера: приём задач обработки файлов."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import config
from app.services.file_processor_bg import process_files_background

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal-worker"])


class ProcessFilesRequest(BaseModel):
    file_ids: list[str] = Field(..., min_length=1)
    case_id: str = Field(..., min_length=1)


def _verify_worker_secret(provided: str | None) -> None:
    expected = config.INTERNAL_WORKER_SECRET
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="INTERNAL_WORKER_SECRET is not configured on worker",
        )
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Invalid worker secret")


@router.post("/process-files", status_code=202)
async def enqueue_process_files(
    body: ProcessFilesRequest,
    x_internal_worker_secret: str = Header(default="", alias="X-Internal-Worker-Secret"),
):
    """Принять пачку file_ids и обработать в фоне (OCR → индекс → ready)."""
    _verify_worker_secret(x_internal_worker_secret or None)
    file_ids = body.file_ids
    case_id = body.case_id

    async def _run() -> None:
        try:
            await asyncio.to_thread(process_files_background, file_ids, case_id)
        except Exception as exc:
            logger.error(
                "Worker processing failed for case %s: %s",
                case_id,
                exc,
                exc_info=True,
            )

    asyncio.create_task(_run())
    logger.info(
        "Worker accepted %s file(s) for case %s",
        len(file_ids),
        case_id,
    )
    return {
        "status": "accepted",
        "file_ids": file_ids,
        "case_id": case_id,
    }
