"""
HTTP helpers for serving stored case file originals (disk-first, DB fallback).

Single read path for preview (/content), download, and worker — via load_case_file_bytes.
"""
from __future__ import annotations

import logging
import mimetypes
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import Response

from app.services.case_file_bytes import load_case_file_bytes

if TYPE_CHECKING:
    from app.models.case import File

logger = logging.getLogger(__name__)

_EXT_MEDIA_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint",
    "txt": "text/plain",
    "rtf": "application/rtf",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "webp": "image/webp",
    "zip": "application/zip",
    "rar": "application/x-rar-compressed",
    "7z": "application/x-7z-compressed",
}


def case_file_media_type(file: "File") -> str:
    guessed, _ = mimetypes.guess_type(file.filename or "")
    if guessed:
        return guessed
    ext = (file.file_type or "").lower()
    if not ext and file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    return _EXT_MEDIA_TYPES.get(ext, "application/octet-stream")


def case_file_content_disposition(filename: str, *, attachment: bool) -> str:
    encoded = quote(filename or "document", safe="")
    mode = "attachment" if attachment else "inline"
    return f"{mode}; filename*=UTF-8''{encoded}"


def load_case_original_bytes(file: "File") -> bytes:
    """Return stored original bytes or raise HTTPException (no synthetic PDF from OCR text)."""
    raw = load_case_file_bytes(file)
    if raw:
        return raw
    ext = (file.file_type or "").lower()
    if ext == "pdf" or (file.filename or "").lower().endswith(".pdf"):
        logger.warning(
            "Original PDF missing file_id=%s filename=%s path=%s",
            getattr(file, "id", None),
            file.filename,
            file.file_path,
        )
        raise HTTPException(
            status_code=404,
            detail=(
                f"Оригинальный файл не найден на сервере. "
                f"Загрузите документ заново или проверьте хранилище (UPLOAD_DIR). "
                f"Файл: {file.filename}"
            ),
        )
    raise HTTPException(
        status_code=404,
        detail=f"Оригинальный файл недоступен. Файл: {file.filename}",
    )


def case_file_bytes_response(
    file: "File",
    *,
    inline: bool,
) -> Response:
    """Stream the persisted original (disk or DB blob)."""
    body = load_case_original_bytes(file)
    return Response(
        content=body,
        media_type=case_file_media_type(file),
        headers={
            "Content-Disposition": case_file_content_disposition(
                file.filename or "document",
                attachment=not inline,
            ),
            "X-Case-File-Source": "original",
        },
    )


def case_file_text_fallback_response(file: "File", *, inline: bool) -> Response:
    """
    Legacy rows without stored bytes: serve extracted text only (non-PDF).
    UI should show that the original was not preserved.
    """
    if not file.original_text:
        raise HTTPException(status_code=404, detail="Содержимое файла недоступно")
    return Response(
        content=file.original_text.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": case_file_content_disposition(
                file.filename or "document",
                attachment=not inline,
            ),
            "X-Case-File-Source": "extracted-text",
        },
    )
