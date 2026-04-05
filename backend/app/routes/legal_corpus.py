"""Загрузка и управление общим правовым справочником (только для указанных email)."""
import logging
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models.user import User
from app.services import legal_corpus_service as lcs
from app.utils.auth import get_current_user
from app.utils.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legal-corpus"])

MAX_FILES_PER_REQUEST = 15


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


@router.post("/api/v2/legal-corpus/upload")
async def legal_corpus_upload(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Индексация одного или нескольких файлов в общий правовой справочник.
    """
    _ = db  # сессия для единообразия с остальными роутами
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
            corpus_file_id, chunks = lcs.index_uploaded_file(content, f.filename)
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = db
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
