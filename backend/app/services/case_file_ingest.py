"""Shared case file persistence + background processing (local upload, Google Drive, etc.)."""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import config
from app.models.case import Case, File as FileModel
from app.services.case_file_bytes import case_file_content_for_db

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestedCaseFile:
    file_id: str
    filename: str
    absolute_path: str


def sanitize_upload_filename(name: str) -> str:
    """Strip path segments and dangerous chars; cap length for DB/disk."""
    cleaned = (name or "document").replace("..", "").replace("/", "").replace("\\", "").strip()
    if not cleaned:
        cleaned = "document"
    return cleaned[:255]


def file_extension(filename: str) -> str:
    if "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return ""


def is_allowed_extension(ext: str) -> bool:
    allowed = {e.lstrip(".").lower() for e in config.ALLOWED_EXTENSIONS}
    return ext.lower() in allowed


def case_upload_dir(case_id: str) -> str:
    upload_dir = config.UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, case_id)
    os.makedirs(path, exist_ok=True)
    return path


def unique_disk_path(case_dir: str, filename: str) -> Tuple[str, str]:
    """
    Return (absolute_path, final_filename).
    If name collides, append (1), (2), … before extension.
    """
    base, ext = os.path.splitext(filename)
    candidate = filename
    abs_path = os.path.join(case_dir, candidate)
    n = 1
    while os.path.exists(abs_path):
        candidate = f"{base} ({n}){ext}" if ext else f"{base} ({n})"
        abs_path = os.path.join(case_dir, candidate)
        n += 1
    return abs_path, candidate


def persist_case_file_bytes(
    db: Session,
    *,
    case_id: str,
    filename: str,
    content: bytes,
    reconnect_db,
) -> IngestedCaseFile:
    """
    Write bytes to UPLOAD_DIR, create File row (pending), flush.
    Caller must commit and call schedule_case_files_processing.
    """
    if not content:
        raise ValueError("Пустой файл")

    if len(content) > config.MAX_FILE_SIZE:
        max_mb = config.MAX_FILE_SIZE / 1024 / 1024
        raise ValueError(f"Файл слишком большой. Максимум: {max_mb:.0f} МБ")

    safe_name = sanitize_upload_filename(filename)
    ext = file_extension(safe_name)
    if not is_allowed_extension(ext):
        allowed = ", ".join(e.lstrip(".") for e in config.ALLOWED_EXTENSIONS)
        raise ValueError(f"Неподдерживаемый формат. Поддерживаются: {allowed}")

    case_dir = case_upload_dir(case_id)
    abs_path, final_name = unique_disk_path(case_dir, safe_name)
    with open(abs_path, "wb") as fh:
        fh.write(content)

    relative_path = os.path.join(case_id, final_name)
    file_type = ext[:50]

    file_model = FileModel(
        case_id=case_id,
        filename=final_name,
        file_type=file_type,
        original_text="",
        file_path=relative_path,
        file_content=case_file_content_for_db(content),
        processing_status="pending",
    )
    try:
        with db.begin_nested():
            db.add(file_model)
            reconnect_db(db)
            db.flush()
    except OperationalError as op_err:
        logger.warning(
            "OperationalError on file flush (case_id=%s, filename=%s): %s",
            case_id,
            final_name,
            op_err,
        )
        reconnect_db(db)
        with db.begin_nested():
            db.add(file_model)
            reconnect_db(db)
            db.flush()

    return IngestedCaseFile(
        file_id=file_model.id,
        filename=final_name,
        absolute_path=abs_path,
    )


def refresh_case_file_metadata(db: Session, case: Case, case_id: str) -> None:
    all_files = db.query(FileModel).filter(FileModel.case_id == case_id).all()
    case.num_documents = len(all_files)
    case.file_names = [f.filename for f in all_files]


def schedule_case_files_processing(case_id: str, file_ids: Sequence[str]) -> None:
    """Same background path as POST /cases/{id}/files."""
    if not file_ids:
        return

    from app.services.file_processor_bg import process_files_background

    async def _bg() -> None:
        try:
            await asyncio.to_thread(process_files_background, list(file_ids), case_id)
        except Exception as exc:
            logger.error(
                "Background processing task error for case %s: %s",
                case_id,
                exc,
                exc_info=True,
            )

    asyncio.create_task(_bg())
    logger.info(
        "Background processing started for %s files in case %s",
        len(file_ids),
        case_id,
    )


def cleanup_absolute_paths(paths: Sequence[str]) -> None:
    for path in paths:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError as exc:
            logger.warning("Failed to cleanup %s: %s", path, exc)
