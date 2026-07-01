"""Background file processor: OCR → passport → index in PGVector.

Each file is processed independently in a bounded thread pool (see
``file_processing_concurrency``). A single call to ``process_files_background``
shares one ``DocumentProcessor`` instance across workers to avoid re-initialising
Yandex embeddings for every file.

Document type is determined during passport generation (one LLM call per file).
"""
from __future__ import annotations

import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.services.file_processing_concurrency import (
    case_metadata_lock,
    document_passport_slot,
    max_parallel_files,
)
from app.utils.database import SessionLocal

logger = logging.getLogger(__name__)


def _sanitize(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\x00", "")
    return "".join(ch for ch in text if ord(ch) >= 32 or ch in "\n\r\t")


def _generate_llm_document_passport(
    *,
    text: str,
    filename: str,
    hint_doc_type: str,
) -> tuple[str, List[str], str, str]:
    """Returns (summary, key_points, doc_type, summary_version)."""
    from app.services.document_passport_graph import generate_document_passport

    with document_passport_slot():
        return generate_document_passport(
            text=text,
            filename=filename,
            hint_doc_type=hint_doc_type,
            max_attempts=3,
        )


def _reconnect(db: Session) -> None:
    from sqlalchemy import text

    try:
        db.execute(text("SELECT 1"))
    except Exception:
        try:
            db.connection().invalidate()
        except Exception:
            pass
        try:
            db.rollback()
        except Exception:
            pass


def process_files_background(file_ids: List[str], case_id: str) -> None:
    """
    Blocking function — run via asyncio.to_thread from the route handler or worker.

    Files in the batch run in parallel (bounded by ``FILE_PROCESSING_MAX_PARALLEL_FILES``).
    Per file:
      1. Load raw bytes (UPLOAD_DIR + file_path, else file_content in DB)
      2. OCR / parse via DocumentLoaderService
      3. Generate document passport (summary, key points, doc_type) — one LLM call
      4. Update original_text in DB
      5. Split + embed + store in PGVector
      6. Mark processing_status = 'ready'

    Case.full_text and Case.status are updated when all files in the batch are done.
    """
    from app.services.document_processor import get_document_processor

    if not file_ids:
        return

    document_processor = None
    prewarm_documents: List[Document] = []
    prewarm_lock = threading.Lock()

    try:
        try:
            document_processor = get_document_processor()
        except Exception as e:
            logger.error(
                "Cannot initialise DocumentProcessor for case %s: %s",
                case_id,
                e,
                exc_info=True,
            )
            err_db = SessionLocal()
            try:
                for fid in file_ids:
                    _set_error(err_db, fid, f"Ошибка инициализации обработчика: {e}")
            finally:
                err_db.close()
            return

        workers = min(max_parallel_files(), len(file_ids))

        def _worker(file_id: str) -> List[Document]:
            db = SessionLocal()
            try:
                return _process_one_file(db, file_id, case_id, document_processor)
            except Exception as exc:
                logger.error(
                    "Unhandled error processing file %s: %s",
                    file_id,
                    exc,
                    exc_info=True,
                )
                _set_error(db, file_id, str(exc)[:1000])
                return []
            finally:
                db.close()

        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="file-ingest",
        ) as pool:
            futures = {pool.submit(_worker, fid): fid for fid in file_ids}
            for fut in as_completed(futures):
                file_id = futures[fut]
                try:
                    file_documents = fut.result()
                except Exception as exc:
                    logger.error(
                        "Worker future failed for file %s: %s",
                        file_id,
                        exc,
                        exc_info=True,
                    )
                    continue
                if file_documents:
                    with prewarm_lock:
                        prewarm_documents.extend(file_documents)

        stats_db = SessionLocal()
        try:
            _update_case_stats(stats_db, case_id)
        finally:
            stats_db.close()

        if prewarm_documents and document_processor is not None:
            document_processor.prewarm_bm25_index(
                case_id,
                documents=prewarm_documents,
                force_rebuild=True,
            )

    except Exception as exc:
        logger.error(
            "process_files_background failed for case %s: %s",
            case_id,
            exc,
            exc_info=True,
        )


def _persist_passport_classification(
    db: Session,
    *,
    case_id: str,
    file_id: str,
    doc_type: str,
    key_points: List[str],
    passport_version: str,
) -> None:
    """Store document classification derived from the passport (single source of truth)."""
    from app.models.analysis import DocumentClassification

    existing = (
        db.query(DocumentClassification)
        .filter(DocumentClassification.file_id == file_id)
        .first()
    )
    if existing:
        return

    topics = [str(p).strip() for p in (key_points or []) if str(p).strip()][:8]
    db.add(
        DocumentClassification(
            case_id=case_id,
            file_id=file_id,
            doc_type=doc_type or "прочее",
            relevance_score=0,
            is_privileged="false",
            privilege_type="none",
            key_topics=topics,
            confidence="1.0",
            reasoning="Тип и ключевые тезисы определены при генерации паспорта документа.",
            needs_human_review="false",
            prompt_version=passport_version or "v3_langgraph_llm",
        )
    )


def _process_one_file(
    db: Session,
    file_id: str,
    case_id: str,
    document_processor,
) -> List[Document]:
    from app.services.langchain_loaders import DocumentLoaderService
    from app.services.document_passport_hint import infer_doc_type_hint_from_filename
    from app.services.chat.entity_index_service import merge_case_entity_index
    from app.models.case import Case, File as FileModel

    _reconnect(db)

    file_model = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not file_model:
        logger.error("File %s not found in DB", file_id)
        return []

    filename = file_model.filename

    if file_model.processing_status == "cancelled":
        logger.info("File %s (%s) was cancelled, skipping", file_id, filename)
        return []

    from app.services.case_file_bytes import load_case_file_bytes

    content = load_case_file_bytes(file_model)
    if not content:
        logger.error(
            "File %s (%s): bytes unavailable (file_path=%r, db_blob=%s)",
            file_id,
            filename,
            file_model.file_path,
            bool(file_model.file_content),
        )
        _set_error(
            db,
            file_id,
            "Не удалось прочитать файл: проверьте UPLOAD_DIR и наличие файла на диске",
        )
        return []

    from datetime import datetime as _dt

    file_model.processing_status = "processing"
    file_model.processing_started_at = _dt.utcnow()
    db.commit()
    logger.info("▶ Processing file %s (%s), %s bytes", file_id, filename, len(content))

    try:
        langchain_docs = DocumentLoaderService.load_document(content, filename)
    except Exception as e:
        logger.error("OCR failed for %s (%s): %s", filename, file_id, e, exc_info=True)
        _set_error(db, file_id, f"Ошибка OCR: {str(e)[:800]}")
        return []

    if not langchain_docs:
        _set_error(db, file_id, "Файл не содержит текста или не может быть прочитан")
        return []

    text = "\n\n".join(doc.page_content for doc in langchain_docs)
    text = _sanitize(text)

    if not text.strip():
        _set_error(db, file_id, "Файл не содержит текста после обработки")
        return []

    max_text = 50 * 1024 * 1024
    if len(text) > max_text:
        logger.warning(
            "File %s text truncated from %s to %s chars",
            filename,
            len(text),
            max_text,
        )
        text = text[:max_text]

    doc_type_hint = infer_doc_type_hint_from_filename(filename)

    _reconnect(db)
    file_model = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not file_model:
        return []
    if file_model.processing_status == "cancelled":
        logger.info("File %s (%s) was cancelled during OCR, skipping", file_id, filename)
        return []

    try:
        (
            passport_summary,
            passport_key_points,
            passport_doc_type,
            passport_version,
        ) = _generate_llm_document_passport(
            text=text,
            filename=filename,
            hint_doc_type=doc_type_hint,
        )
    except Exception as e:
        logger.error(
            "Document passport generation failed for %s (%s): %s",
            filename,
            file_id,
            e,
            exc_info=True,
        )
        _set_error(
            db,
            file_id,
            (
                "Ошибка генерации паспорта документа через LLM. "
                "Паспорт обязателен и не может быть заменен фрагментом текста. "
                f"Детали: {str(e)[:400]}"
            ),
        )
        return []

    if not str(passport_summary or "").strip():
        _set_error(
            db,
            file_id,
            (
                "Ошибка генерации паспорта документа через LLM: пустое summary. "
                "Паспорт обязателен, fallback отключен."
            ),
        )
        return []
    if not isinstance(passport_key_points, list) or not passport_key_points:
        _set_error(
            db,
            file_id,
            (
                "Ошибка генерации паспорта документа через LLM: отсутствуют key points. "
                "Паспорт обязателен, fallback отключен."
            ),
        )
        return []

    logger.info(
        "Document passport generated for %s: version=%s summary_len=%s key_points=%s doc_type=%s",
        filename,
        passport_version,
        len(passport_summary or ""),
        len(passport_key_points or []),
        passport_doc_type,
    )

    file_model.original_text = text
    file_model.doc_summary_short = passport_summary
    file_model.doc_key_points = passport_key_points
    file_model.summary_version = passport_version
    file_model.summary_content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    with case_metadata_lock(case_id):
        case_model = db.query(Case).filter(Case.id == case_id).first()
        if case_model:
            merge_case_entity_index(
                case_model,
                file_id=file_id,
                filename=filename,
                text=text,
            )
    db.flush()

    try:
        _persist_passport_classification(
            db,
            case_id=case_id,
            file_id=file_id,
            doc_type=passport_doc_type,
            key_points=passport_key_points,
            passport_version=passport_version,
        )
    except Exception as e:
        logger.warning("Could not save classification for %s: %s", filename, e)

    db.commit()
    logger.info("✅ Text saved for %s (%s), %s chars", filename, file_id, len(text))

    try:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
        metadata = {
            "case_id": case_id,
            "file_id": file_id,
            "file_type": ext,
            "doc_type": passport_doc_type or doc_type_hint,
        }

        file_documents = document_processor.split_documents(
            text=text,
            filename=filename,
            metadata=metadata,
            file_id=file_id,
            langchain_docs=langchain_docs,
            content_bytes=content,
        )

        if not file_documents:
            _set_error(
                db,
                file_id,
                (
                    "Ошибка чанкинга: не удалось сформировать ни одного чанка. "
                    "Fallback-режимы отключены, загрузка остановлена."
                ),
            )
            return []

        _reconnect(db)
        document_processor.store_in_vector_db(
            case_id=case_id,
            documents=file_documents,
            db=db,
            bm25_after_store="invalidate_only",
        )
        docling_count = sum(
            1 for d in file_documents if d.metadata.get("chunk_level") == "docling"
        )
        logger.info(
            "✅ Indexed %s chunks for %s (docling=%s)",
            len(file_documents),
            filename,
            docling_count,
        )
    except Exception as e:
        logger.error("Indexing failed for %s (%s): %s", filename, file_id, e, exc_info=True)
        _set_error(db, file_id, f"Ошибка индексирования: {str(e)[:500]}")
        return []

    _reconnect(db)
    file_model = db.query(FileModel).filter(FileModel.id == file_id).first()
    if file_model:
        file_model.processing_status = "ready"
        file_model.processing_error = None
        db.commit()
    logger.info("✅ File %s (%s) is ready", file_id, filename)
    return file_documents


def _set_error(db: Session, file_id: str, message: str) -> None:
    from app.models.case import File as FileModel

    try:
        _reconnect(db)
        file_model = db.query(FileModel).filter(FileModel.id == file_id).first()
        if file_model:
            file_model.processing_status = "error"
            file_model.processing_error = message
            db.commit()
    except Exception as e:
        logger.error("Could not set error status for file %s: %s", file_id, e)


def _update_case_stats(db: Session, case_id: str) -> None:
    from app.models.case import File as FileModel, Case

    try:
        _reconnect(db)
        files = db.query(FileModel).filter(FileModel.case_id == case_id).all()
        if not files:
            return

        text_parts = [
            f"[{f.filename}]\n{f.original_text}"
            for f in files
            if f.original_text and f.original_text.strip()
        ]

        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            return

        if text_parts:
            full_text = "\n\n".join(text_parts)
            full_text = _sanitize(full_text)
            max_text = 100 * 1024 * 1024
            if len(full_text) > max_text:
                full_text = full_text[:max_text]
            case.full_text = full_text

        pending = [f for f in files if f.processing_status in ("pending", "processing")]
        errors = [f for f in files if f.processing_status == "error"]
        ready = [f for f in files if f.processing_status == "ready"]

        if not pending:
            if errors and not ready:
                case.status = "failed"
            elif errors:
                case.status = "completed_with_errors"
            else:
                case.status = "completed"

        case.num_documents = len(files)
        case.file_names = [f.filename for f in files]
        db.commit()
        logger.info(
            "Case %s stats updated: %s files, status=%s",
            case_id,
            len(files),
            case.status,
        )
    except Exception as e:
        logger.error("Could not update case stats for %s: %s", case_id, e, exc_info=True)
