"""Background file processor: OCR → classify → index in PGVector.

Each file is processed independently. A single call to process_files_background
handles a batch of file IDs sequentially, sharing one DocumentProcessor instance
to avoid re-initialising Yandex embeddings for every file.
"""
from __future__ import annotations

import logging
from typing import List
import hashlib

from sqlalchemy.orm import Session

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
    Blocking function — run via asyncio.to_thread from the route handler.

    For each file_id:
      1. Load raw bytes from DB (file_content)
      2. OCR / parse via DocumentLoaderService
      3. Classify
      4. Update original_text in DB
      5. Split + embed + store in PGVector
      6. Mark processing_status = 'ready'

    Case.full_text and Case.status are updated when all files are done.
    """
    from app.services.langchain_loaders import DocumentLoaderService
    from app.services.document_classifier_service import DocumentClassifierService
    from app.services.document_processor import DocumentProcessor, get_document_processor
    from app.services.chat.entity_index_service import merge_case_entity_index
    from app.models.case import File as FileModel, Case
    from app.models.analysis import DocumentClassification

    db = SessionLocal()
    document_processor: DocumentProcessor | None = None
    prewarm_documents = []

    try:
        # Initialise DocumentProcessor once for the whole batch (expensive: YandexEmbeddings)
        try:
            document_processor = get_document_processor()
        except Exception as e:
            logger.error(f"Cannot initialise DocumentProcessor for case {case_id}: {e}", exc_info=True)
            # Mark all files as error
            for fid in file_ids:
                _set_error(db, fid, f"Ошибка инициализации обработчика: {e}")
            return

        for file_id in file_ids:
            try:
                file_documents = _process_one_file(db, file_id, case_id, document_processor)
                if file_documents:
                    prewarm_documents.extend(file_documents)
            except Exception as e:
                logger.error(f"Unhandled error processing file {file_id}: {e}", exc_info=True)
                _set_error(db, file_id, str(e)[:1000])

        # After all files are processed, update Case stats
        _update_case_stats(db, case_id)
        if prewarm_documents:
            document_processor.prewarm_bm25_index(
                case_id,
                documents=prewarm_documents,
                force_rebuild=True,
            )

    finally:
        db.close()


def _process_one_file(
    db: Session,
    file_id: str,
    case_id: str,
    document_processor,
) -> None:
    from app.services.langchain_loaders import DocumentLoaderService
    from app.services.document_classifier_service import DocumentClassifierService
    from app.services.chat.entity_index_service import merge_case_entity_index
    from app.models.case import Case, File as FileModel
    from app.models.analysis import DocumentClassification

    _reconnect(db)

    file_model = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not file_model:
        logger.error(f"File {file_id} not found in DB")
        return []

    filename = file_model.filename
    content: bytes | None = file_model.file_content

    if not content:
        logger.error(f"File {file_id} ({filename}) has no binary content stored")
        _set_error(db, file_id, "Нет содержимого файла в базе данных")
        return []

    # Check if cancelled before starting
    if file_model.processing_status == "cancelled":
        logger.info(f"File {file_id} ({filename}) was cancelled, skipping")
        return []

    # Mark as processing
    from datetime import datetime as _dt
    file_model.processing_status = "processing"
    file_model.processing_started_at = _dt.utcnow()
    db.commit()
    logger.info(f"▶ Processing file {file_id} ({filename}), {len(content)} bytes")

    # --- OCR / parse ---
    try:
        langchain_docs = DocumentLoaderService.load_document(content, filename)
    except Exception as e:
        logger.error(f"OCR failed for {filename} ({file_id}): {e}", exc_info=True)
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

    MAX_TEXT = 50 * 1024 * 1024
    if len(text) > MAX_TEXT:
        logger.warning(f"File {filename} text truncated from {len(text)} to {MAX_TEXT} chars")
        text = text[:MAX_TEXT]

    # --- Classify ---
    file_classification: dict = {
        "doc_type": "other", "tags": [], "confidence": 0.0,
        "needs_human_review": True, "reasoning": "",
    }
    try:
        classifier = DocumentClassifierService()
        file_classification = classifier.classify_document(text=text, filename=filename, case_context=None)
        logger.info(f"Classified {filename}: {file_classification.get('doc_type')} ({file_classification.get('confidence', 0):.2f})")
    except Exception as e:
        logger.warning(f"Classification failed for {filename}: {e}")

    # --- Save text to DB ---
    _reconnect(db)
    file_model = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not file_model:
        return []
    # Re-check if cancelled during OCR (which can take minutes)
    if file_model.processing_status == "cancelled":
        logger.info(f"File {file_id} ({filename}) was cancelled during OCR, skipping")
        return []
    try:
        passport_summary, passport_key_points, passport_doc_type, passport_version = _generate_llm_document_passport(
            text=text,
            filename=filename,
            hint_doc_type=file_classification.get("doc_type", "other"),
        )
    except Exception as e:
        logger.error("Document passport generation failed for %s (%s): %s", filename, file_id, e, exc_info=True)
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
    case_model = db.query(Case).filter(Case.id == case_id).first()
    if case_model:
        merge_case_entity_index(
            case_model,
            file_id=file_id,
            filename=filename,
            text=text,
        )
    db.flush()

    # Save classification
    try:
        existing = db.query(DocumentClassification).filter(
            DocumentClassification.file_id == file_id
        ).first()
        if not existing:
            doc_cls = DocumentClassification(
                case_id=case_id,
                file_id=file_id,
                doc_type=passport_doc_type or file_classification.get("doc_type", "other"),
                relevance_score=0,
                is_privileged="false",
                privilege_type="none",
                key_topics=file_classification.get("tags", []),
                confidence=str(file_classification.get("confidence", 0.0)),
                reasoning=file_classification.get("reasoning", ""),
                needs_human_review="true" if file_classification.get("needs_human_review") else "false",
                prompt_version="v1",
            )
            db.add(doc_cls)
    except Exception as e:
        logger.warning(f"Could not save classification for {filename}: {e}")

    db.commit()
    logger.info(f"✅ Text saved for {filename} ({file_id}), {len(text)} chars")

    # --- Build direct Docling chunks + embed + index ---
    try:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
        metadata = {
            "case_id": case_id,
            "file_id": file_id,
            "file_type": ext,
            "doc_type": file_classification.get("doc_type", "other"),
        }

        file_documents = document_processor.split_documents(
            text=text,
            filename=filename,
            metadata=metadata,
            file_id=file_id,
            langchain_docs=langchain_docs,
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
        )
        docling_count = sum(1 for d in file_documents if d.metadata.get("chunk_level") == "docling")
        logger.info(
            "✅ Indexed %s chunks for %s (docling=%s)",
            len(file_documents),
            filename,
            docling_count,
        )
    except Exception as e:
        logger.error(f"Indexing failed for {filename} ({file_id}): {e}", exc_info=True)
        _set_error(db, file_id, f"Ошибка индексирования: {str(e)[:500]}")
        return []

    # Mark ready
    _reconnect(db)
    file_model = db.query(FileModel).filter(FileModel.id == file_id).first()
    if file_model:
        file_model.processing_status = "ready"
        file_model.processing_error = None
        db.commit()
    logger.info(f"✅ File {file_id} ({filename}) is ready")
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
        logger.error(f"Could not set error status for file {file_id}: {e}")


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
            MAX_TEXT = 100 * 1024 * 1024
            if len(full_text) > MAX_TEXT:
                full_text = full_text[:MAX_TEXT]
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
        logger.info(f"Case {case_id} stats updated: {len(files)} files, status={case.status}")
    except Exception as e:
        logger.error(f"Could not update case stats for {case_id}: {e}", exc_info=True)
