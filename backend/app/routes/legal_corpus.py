"""Загрузка и управление общим правовым справочником (только для указанных email)."""
import logging
import asyncio
import os
import time
import functools
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi import Form
from fastapi.responses import Response

from app.models.user import User
from app.services import legal_corpus_service as lcs
from app.services.legal_corpus_jobs import legal_corpus_job_store
from app.utils.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legal-corpus"])

MAX_FILES_PER_REQUEST = 15
_JOB_TMP_PREFIX = "legal-corpus-jobs"


def _safe_job_filename(name: str) -> str:
    n = (name or "document").replace("..", "").replace("/", "").replace("\\", "")
    return n or "document"


async def _run_legal_corpus_job(
    *,
    job_id: str,
    file_paths: List[str],
    file_names: List[str],
    user_id: str,
    instrument_id: str | None = None,
) -> None:
    """
    Background worker for legal corpus indexing.
    Writes progress into in-memory job store (SSE queue).
    """
    job = await legal_corpus_job_store.get_job(job_id)
    if not job:
        return
    job.status = "running"
    job.message = "Индексация запущена…"
    job.progress_percent = 0.0
    await legal_corpus_job_store.emit(
        job,
        {"type": "status", "job_id": job_id, "status": job.status, "progress_percent": job.progress_percent, "message": job.message},
    )

    started = time.time()
    try:
        for idx, (path, name) in enumerate(zip(file_paths, file_names), start=1):
            job.message = f"Обработка файла {idx}/{job.total_files}: {name}"
            await legal_corpus_job_store.emit(
                job,
                {
                    "type": "file_started",
                    "job_id": job_id,
                    "file_index": idx,
                    "total_files": job.total_files,
                    "filename": name,
                    "message": job.message,
                },
            )

            with open(path, "rb") as f:
                content = f.read()

            file_total_indexed = 0

            def _cb(ev: dict) -> None:
                nonlocal file_total_indexed
                if ev.get("event") == "chunks_indexed":
                    file_total_indexed = int(ev.get("total_indexed") or file_total_indexed)

            # Docling + embeddings are CPU/blocking; run off the asyncio loop so
            # POST /upload-job can return immediately and SSE clients stay responsive.
            corpus_file_id, chunks = await asyncio.to_thread(
                functools.partial(
                    lcs.index_uploaded_file,
                    content,
                    name,
                    created_by_user_id=user_id,
                    instrument_id=instrument_id,
                    progress_cb=_cb,
                )
            )

            job.results.append({"filename": name, "corpus_file_id": corpus_file_id, "chunks_indexed": int(chunks)})
            job.indexed_chunks += int(chunks)
            job.processed_files = idx
            job.progress_percent = round((idx / max(1, job.total_files)) * 100.0, 1)
            await legal_corpus_job_store.emit(
                job,
                {
                    "type": "file_completed",
                    "job_id": job_id,
                    "file_index": idx,
                    "total_files": job.total_files,
                    "filename": name,
                    "corpus_file_id": corpus_file_id,
                    "chunks_indexed": int(chunks),
                    "progress_percent": job.progress_percent,
                    "message": f"Файл проиндексирован: {name} ({chunks} чанков)",
                },
            )

        job.status = "completed"
        job.message = "Индексация справочника завершена."
        job.progress_percent = 100.0
        job.finished_at = time.time()
        await legal_corpus_job_store.emit(
            job,
            {
                "type": "completed",
                "job_id": job_id,
                "status": job.status,
                "progress_percent": job.progress_percent,
                "message": job.message,
                "duration_sec": round(job.finished_at - started, 2),
                "results": job.results,
                "errors": job.errors,
                "indexed_chunks": job.indexed_chunks,
                "chunk_count_total": lcs.count_corpus_chunks(),
            },
        )
    except Exception as e:
        job.status = "failed"
        job.message = f"Ошибка индексации: {e!s}"
        job.finished_at = time.time()
        job.errors.append({"filename": file_names[job.processed_files] if job.processed_files < len(file_names) else "", "detail": str(e)})
        await legal_corpus_job_store.emit(
            job,
            {
                "type": "failed",
                "job_id": job_id,
                "status": job.status,
                "progress_percent": job.progress_percent,
                "message": job.message,
                "duration_sec": round(job.finished_at - started, 2),
                "results": job.results,
                "errors": job.errors,
            },
        )
    finally:
        # Best-effort cleanup of temp files
        for p in file_paths:
            try:
                os.remove(p)
            except Exception:
                pass
        try:
            job_dir = os.path.dirname(file_paths[0]) if file_paths else ""
            if job_dir and os.path.exists(job_dir) and not os.listdir(job_dir):
                os.rmdir(job_dir)
        except Exception:
            pass
        # Tell SSE stream to close if client wants
        await legal_corpus_job_store.emit(job, {"type": "done", "job_id": job_id})


def _require_uploader(user: User) -> None:
    if not lcs.is_legal_corpus_uploader(user):
        raise HTTPException(
            status_code=403,
            detail="Загрузка справочника доступна только уполномоченным пользователям.",
        )


@router.get("/api/v2/legal-corpus/status")
async def legal_corpus_status(current_user: User = Depends(get_current_user)):
    """
    Для любого авторизованного пользователя: есть ли проиндексированный справочник,
    может ли текущий пользователь загружать файлы.
    """
    try:
        chunk_count = lcs.count_corpus_chunks()
    except Exception as e:
        logger.error("legal_corpus_status count failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Не удалось проверить справочник. Повторите позже.")

    return {
        "chunk_count": chunk_count,
        "has_corpus": chunk_count > 0,
        "is_uploader": lcs.is_legal_corpus_uploader(current_user),
    }


@router.get("/api/v2/legal-corpus/files")
async def legal_corpus_files(current_user: User = Depends(get_current_user)):
    """Список файлов справочника — только для уполномоченного загрузчика."""
    _require_uploader(current_user)
    try:
        files = lcs.list_corpus_files()
    except Exception as e:
        logger.error("legal_corpus_files list failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Не удалось получить список файлов.")
    return {"files": files}


@router.get("/api/v2/legal-corpus/instruments")
async def legal_corpus_instruments(current_user: User = Depends(get_current_user)):
    """
    Справочник актов для загрузки/роутинга: instrument_id -> label/aliases.
    Доступен любому авторизованному пользователю (чтобы UI мог отрисовать список),
    но загружать файлы всё равно могут только uploader-аккаунты.
    """
    _ = current_user
    from app.services.legal_instruments import list_instruments_for_api

    return {"instruments": list_instruments_for_api()}


@router.post("/api/v2/legal-corpus/upload-job")
async def legal_corpus_upload_job(
    files: List[UploadFile] = File(...),
    instrument_id: str | None = Form(None),
    current_user: User = Depends(get_current_user),
):
    """
    Async upload: returns job_id immediately; progress is streamed via SSE.
    """
    _require_uploader(current_user)
    if not files:
        raise HTTPException(status_code=400, detail="Не переданы файлы")
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"За один раз не более {MAX_FILES_PER_REQUEST} файлов")
    try:
        lcs.assert_embeddings_available()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    job = await legal_corpus_job_store.create_job(total_files=len(files))

    # Save to tmp folder to avoid keeping huge bytes in memory.
    from app.config import config

    base_dir = os.path.join(str(config.UPLOAD_DIR), _JOB_TMP_PREFIX, job.job_id)
    os.makedirs(base_dir, exist_ok=True)
    file_paths: List[str] = []
    file_names: List[str] = []
    for f in files:
        if not f.filename:
            continue
        name = _safe_job_filename(f.filename)
        content = await f.read()
        path = os.path.join(base_dir, name)
        with open(path, "wb") as out:
            out.write(content)
        file_paths.append(path)
        file_names.append(name)

    if not file_paths:
        raise HTTPException(status_code=400, detail="Не удалось прочитать файлы")

    # Emit + return HTTP before scheduling work: otherwise the background task can
    # start Docling on the same loop and block the response until conversion finishes.
    await legal_corpus_job_store.emit(
        job,
        {"type": "queued", "job_id": job.job_id, "status": job.status, "message": "Job создан, ожидание запуска…"},
    )
    asyncio.create_task(
        _run_legal_corpus_job(
            job_id=job.job_id,
            file_paths=file_paths,
            file_names=file_names,
            user_id=str(current_user.id),
            instrument_id=instrument_id,
        )
    )
    return {"job_id": job.job_id, "status": job.status, "total_files": job.total_files}


@router.get("/api/v2/legal-corpus/jobs/{job_id}")
async def legal_corpus_job_status(job_id: str, current_user: User = Depends(get_current_user)):
    _ = current_user
    job = await legal_corpus_job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.snapshot()


@router.get("/api/v2/legal-corpus/jobs/{job_id}/events")
async def legal_corpus_job_events(
    job_id: str,
    token: str | None = None,
):
    """
    SSE stream for legal corpus job progress.
    EventSource doesn't support headers; pass JWT as ?token=...
    """
    from fastapi.responses import StreamingResponse
    from app.utils.database import SessionLocal
    from app.utils.auth import get_user_from_token

    if not token:
        raise HTTPException(status_code=401, detail="Token required. Pass it via ?token= for SSE")
    db = SessionLocal()
    try:
        user = await get_user_from_token(token, db)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        # Only uploader users should see progress (same as upload permissions)
        _require_uploader(user)
    finally:
        db.close()

    job = await legal_corpus_job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def gen():
        # Open marker + initial snapshot
        yield ": stream-open\n\n"
        yield legal_corpus_job_store.sse_data({"type": "snapshot", **job.snapshot()})
        last_keepalive = time.monotonic()
        while True:
            try:
                msg = await asyncio.wait_for(job.events.get(), timeout=15.0)
                if msg:
                    yield msg
                    if '"type": "done"' in msg or '"type":"done"' in msg:
                        return
            except asyncio.TimeoutError:
                now = time.monotonic()
                if now - last_keepalive >= 15.0:
                    yield ": keepalive\n\n"
                    last_keepalive = now

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/v2/legal-corpus/upload")
async def legal_corpus_upload(
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Индексация одного или нескольких файлов в общий правовой справочник.
    """
    _require_uploader(current_user)

    if not files:
        raise HTTPException(status_code=400, detail="Не переданы файлы")

    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"За один раз не более {MAX_FILES_PER_REQUEST} файлов",
        )

    try:
        lcs.assert_embeddings_available()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    results = []
    errors = []

    for f in files:
        if not f.filename:
            errors.append({"filename": "", "detail": "Пустое имя файла"})
            continue
        try:
            content = await f.read()
            corpus_file_id, chunks = lcs.index_uploaded_file(
                content,
                f.filename,
                created_by_user_id=str(current_user.id),
            )
            results.append(
                {
                    "filename": f.filename,
                    "corpus_file_id": corpus_file_id,
                    "chunks_indexed": chunks,
                }
            )
        except ValueError as e:
            logger.warning("Legal corpus upload validation: %s — %s", f.filename, e)
            errors.append({"filename": f.filename, "detail": str(e)})
        except Exception as e:
            logger.error("Legal corpus upload failed: %s — %s", f.filename, e, exc_info=True)
            errors.append({"filename": f.filename, "detail": f"Ошибка индексации: {e!s}"})

    return {
        "indexed": results,
        "errors": errors,
        "chunk_count_total": lcs.count_corpus_chunks(),
    }


@router.delete("/api/v2/legal-corpus/file/{corpus_file_id}")
async def legal_corpus_delete_file(
    corpus_file_id: str,
    current_user: User = Depends(get_current_user),
):
    _require_uploader(current_user)
    if not corpus_file_id or len(corpus_file_id) > 80:
        raise HTTPException(status_code=400, detail="Некорректный идентификатор")

    try:
        removed = lcs.delete_corpus_file(corpus_file_id)
    except Exception as e:
        logger.error("legal_corpus delete failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Не удалось удалить файл из справочника.")

    if removed == 0:
        raise HTTPException(status_code=404, detail="Файл не найден в справочнике")

    return {"deleted_chunks": removed, "chunk_count_total": lcs.count_corpus_chunks()}


@router.delete("/api/v2/legal-corpus/files")
async def legal_corpus_delete_all(
    current_user: User = Depends(get_current_user),
):
    """Полная очистка правового справочника (все старые кодексы)."""
    _require_uploader(current_user)
    try:
        stats = lcs.delete_all_corpus_files()
    except Exception as e:
        logger.error("legal_corpus delete all failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Не удалось очистить справочник.")
    return {
        **stats,
        "chunk_count_total": lcs.count_corpus_chunks(),
    }


@router.get("/api/v2/legal-corpus-preview/files")
async def legal_corpus_preview_files(current_user: User = Depends(get_current_user)):
    """
    Список файлов для preview в global-assistant.
    Доступен всем авторизованным пользователям (только чтение).
    """
    _ = current_user
    try:
        files = lcs.list_corpus_files()
    except Exception as e:
        logger.error("legal_corpus_preview_files failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Не удалось получить список файлов справочника.")

    return {
        "documents": [
            {
                "id": row.get("corpus_file_id"),
                "filename": row.get("source_filename") or "",
                "file_type": (row.get("file_type") or "txt").lower(),
                "legacy_fallback": not bool(row.get("has_original")),
            }
            for row in files
        ]
    }


@router.get("/api/v2/legal-corpus-preview/files/{corpus_file_id}/content")
async def legal_corpus_preview_file_content(
    corpus_file_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Текстовый контент corpus-файла для подсветки цитат в DocumentPreviewSheet.
    """
    _ = current_user
    try:
        record = lcs.get_corpus_file_record(corpus_file_id)
        file_bytes = lcs.get_corpus_file_bytes(corpus_file_id)
    except Exception as e:
        logger.error("legal_corpus_preview_file_content failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Не удалось загрузить содержимое файла справочника.")

    if file_bytes and record:
        file_type = (record.get("file_type") or "").lower()
        mime_map = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain; charset=utf-8",
            "csv": "text/csv; charset=utf-8",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "json": "application/json; charset=utf-8",
            "xml": "application/xml; charset=utf-8",
            "md": "text/markdown; charset=utf-8",
            "html": "text/html; charset=utf-8",
        }
        media_type = mime_map.get(file_type, "application/octet-stream")
        return Response(content=file_bytes, media_type=media_type)

    # Legacy fallback: старые файлы без сохранённого бинарника
    text_content = lcs.get_corpus_document_text(corpus_file_id)
    if not text_content:
        raise HTTPException(status_code=404, detail="Файл не найден в справочнике")
    return Response(
        content=text_content,
        media_type="text/plain; charset=utf-8",
        headers={"X-Legacy-Fallback": "1"},
    )


@router.get("/api/v2/legal-corpus-preview/files/{corpus_file_id}/download")
async def legal_corpus_preview_file_download(
    corpus_file_id: str,
    current_user: User = Depends(get_current_user),
):
    """Download original file for legal corpus preview panel."""
    _ = current_user
    record = lcs.get_corpus_file_record(corpus_file_id)
    if not record:
        raise HTTPException(status_code=404, detail="Файл не найден в справочнике")
    file_bytes = lcs.get_corpus_file_bytes(corpus_file_id)
    if not file_bytes:
        text_content = lcs.get_corpus_document_text(corpus_file_id)
        if not text_content:
            raise HTTPException(status_code=404, detail="Файл не найден в справочнике")
        filename = (record.get("filename") or f"{corpus_file_id}.txt").rsplit(".", 1)[0] + ".txt"
        return Response(
            content=text_content.encode("utf-8", errors="ignore"),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Legacy-Fallback": "1"},
        )

    file_type = (record.get("file_type") or "").lower()
    mime_map = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain; charset=utf-8",
    }
    media_type = mime_map.get(file_type, "application/octet-stream")
    filename = record.get("filename") or f"{corpus_file_id}.{file_type or 'bin'}"
    return Response(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/v2/legal-corpus-preview/files/{corpus_file_id}/html")
async def legal_corpus_preview_file_html(
    corpus_file_id: str,
    current_user: User = Depends(get_current_user),
):
    """HTML-preview для DOCX из правового корпуса (кэшируется в БД)."""
    _ = current_user
    record = lcs.get_corpus_file_record(corpus_file_id)
    if not record:
        raise HTTPException(status_code=404, detail="Файл не найден в справочнике")
    if (record.get("file_type") or "").lower() != "docx":
        raise HTTPException(status_code=400, detail="HTML preview доступен только для DOCX")

    cached_html = lcs.get_corpus_file_html(corpus_file_id)
    if cached_html:
        return {"html": cached_html, "cached": True, "file_id": corpus_file_id, "filename": record.get("filename")}

    file_bytes = lcs.get_corpus_file_bytes(corpus_file_id)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="Оригинальный DOCX отсутствует (legacy запись)")

    try:
        import io
        import mammoth

        result = mammoth.convert_to_html(io.BytesIO(file_bytes))
        html = result.value
        lcs.set_corpus_file_html(corpus_file_id, html)
        return {"html": html, "cached": False, "file_id": corpus_file_id, "filename": record.get("filename")}
    except Exception as e:
        logger.error("legal_corpus_preview_file_html failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Не удалось конвертировать DOCX в HTML")
