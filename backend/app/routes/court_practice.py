"""Загрузка и управление базой судебной практики (пилот / прод)."""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.models.user import User
from app.services import court_practice_service as cps
from app.services.court_practice_store import get_chunk_preview
from app.services.legal_corpus_jobs import legal_corpus_job_store
from app.utils.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["court-practice"])

_JOB_TMP_PREFIX = "court-practice-jobs"
_MAX_CSV_BYTES = 50 * 1024 * 1024


def _require_uploader(user: User) -> None:
    if not cps.is_court_practice_uploader(user):
        raise HTTPException(
            status_code=403,
            detail="Доступ к загрузке судебной практики есть только у уполномоченных аккаунтов.",
        )


async def _run_index_job(
    *,
    job_id: str,
    file_path: str,
    user_id: str,
    max_rows: Optional[int],
) -> None:
    job = await legal_corpus_job_store.get_job(job_id)
    if not job:
        return
    job.status = "running"
    job.message = "Индексация судебной практики…"
    await legal_corpus_job_store.emit(
        job,
        {"type": "status", "job_id": job_id, "status": job.status, "message": job.message},
    )
    started = time.time()
    try:
        with open(file_path, "rb") as f:
            content = f.read()

        def _progress(ev: dict) -> None:
            if ev.get("event") == "row_indexed":
                idx = int(ev.get("row_index") or 0)
                total = int(ev.get("total_rows") or 1)
                job.progress_percent = round((idx / max(1, total)) * 100.0, 1)
                job.message = f"Строка {idx}/{total}: {ev.get('case_number', '')}"
            if ev.get("event") == "completed":
                job.indexed_chunks = int(ev.get("chunks_indexed") or 0)
                job.processed_files = int(ev.get("documents_indexed") or 0)

        result = await asyncio.to_thread(
            functools.partial(
                cps.index_csv_bytes,
                content,
                created_by_user_id=user_id,
                max_rows=max_rows,
                progress_cb=_progress,
            )
        )
        job.status = "completed"
        job.message = (
            f"Готово: {result['documents_indexed']} документов, "
            f"{result['chunks_indexed']} фрагментов."
        )
        job.progress_percent = 100.0
        job.results.append(result)
        job.finished_at = time.time()
        await legal_corpus_job_store.emit(
            job,
            {
                "type": "completed",
                "job_id": job_id,
                "status": job.status,
                "message": job.message,
                "progress_percent": 100.0,
                "duration_sec": round(job.finished_at - started, 2),
                "results": job.results,
                "errors": job.errors,
                "indexed_chunks": job.indexed_chunks,
                "chunk_count_total": result.get("chunk_count_total"),
            },
        )
    except Exception as exc:
        job.status = "failed"
        job.message = f"Ошибка: {exc!s}"
        job.finished_at = time.time()
        job.errors.append({"detail": str(exc)})
        await legal_corpus_job_store.emit(
            job,
            {
                "type": "failed",
                "job_id": job_id,
                "status": job.status,
                "message": job.message,
                "duration_sec": round(job.finished_at - started, 2),
            },
        )
    finally:
        try:
            os.remove(file_path)
        except OSError:
            pass


@router.get("/api/v2/court-practice/status")
async def court_practice_status(current_user: User = Depends(get_current_user)):
    st = cps.get_status()
    return {
        **st,
        "is_uploader": cps.is_court_practice_uploader(current_user),
    }


@router.post("/api/v2/court-practice/upload-job")
async def court_practice_upload_job(
    file: UploadFile = File(...),
    max_rows: Optional[int] = None,
    current_user: User = Depends(get_current_user),
):
    _require_uploader(current_user)
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Ожидается файл .csv")

    raw = await file.read()
    if len(raw) > _MAX_CSV_BYTES:
        raise HTTPException(status_code=400, detail="CSV слишком большой (лимит 50 МБ)")

    os.makedirs(_JOB_TMP_PREFIX, exist_ok=True)
    safe_name = (file.filename or "upload.csv").replace("..", "").replace("/", "_")
    tmp_path = os.path.join(_JOB_TMP_PREFIX, f"{time.time_ns()}_{safe_name}")
    with open(tmp_path, "wb") as out:
        out.write(raw)

    job = await legal_corpus_job_store.create_job(total_files=1)
    asyncio.create_task(
        _run_index_job(
            job_id=job.job_id,
            file_path=tmp_path,
            user_id=str(current_user.id),
            max_rows=max_rows,
        )
    )
    return {"job_id": job.job_id, "status": job.status}


@router.get("/api/v2/court-practice/jobs/{job_id}/events")
async def court_practice_job_events(
    job_id: str,
    token: str | None = None,
):
    """
    SSE stream for court practice upload job progress.
    EventSource doesn't support headers; pass JWT as ?token=...
    """
    from app.utils.auth import get_user_from_token
    from app.utils.database import SessionLocal

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Token required. Pass it via ?token= for SSE",
        )
    db = SessionLocal()
    try:
        user = await get_user_from_token(token, db)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        _require_uploader(user)
    finally:
        db.close()

    job = await legal_corpus_job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    async def event_stream():
        yield ": stream-open\n\n"
        yield legal_corpus_job_store.sse_data(
            {"type": "status", "job_id": job_id, **job.snapshot()}
        )
        last_keepalive = time.monotonic()
        while True:
            if job.status in ("completed", "failed") and job.events.empty():
                break
            try:
                payload = await asyncio.wait_for(job.events.get(), timeout=25.0)
                yield payload
                if job.status in ("completed", "failed"):
                    await asyncio.sleep(0.05)
                    if job.events.empty():
                        break
            except asyncio.TimeoutError:
                now = time.monotonic()
                if now - last_keepalive >= 15.0:
                    yield ": keepalive\n\n"
                    last_keepalive = now

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/api/v2/court-practice/batch/{batch_id}")
async def court_practice_delete_batch(
    batch_id: str,
    current_user: User = Depends(get_current_user),
):
    _require_uploader(current_user)
    docs, chunks = cps.remove_batch(batch_id)
    return {"deleted_documents": docs, "deleted_chunks": chunks}


@router.delete("/api/v2/court-practice/all")
async def court_practice_delete_all(current_user: User = Depends(get_current_user)):
    _require_uploader(current_user)
    docs, chunks = cps.remove_all()
    return {"deleted_documents": docs, "deleted_chunks": chunks}


@router.get("/api/v2/court-practice/chunk/{chunk_id}")
async def court_practice_chunk_preview(
    chunk_id: str,
    current_user: User = Depends(get_current_user),
):
    row = get_chunk_preview(chunk_id)
    if not row:
        raise HTTPException(status_code=404, detail="Фрагмент не найден")
    return row


@router.get("/api/v2/court-practice-preview")
async def court_practice_preview_query(
    chunk_id: str,
    current_user: User = Depends(get_current_user),
):
    """Совместимость с DocumentPreviewSheet (query param chunk_id)."""
    row = get_chunk_preview(chunk_id)
    if not row:
        raise HTTPException(status_code=404, detail="Фрагмент не найден")
    return {
        "content": row.get("chunk_text") or "",
        "metadata": row,
    }
