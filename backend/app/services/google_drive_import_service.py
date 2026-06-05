"""Download selected Google Drive files and ingest into a case."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.config import config
from app.services.case_file_ingest import (
    file_extension,
    is_allowed_extension,
    sanitize_upload_filename,
)

logger = logging.getLogger(__name__)

# Native Drive MIME → default extension when filename has none
_MIME_TO_EXT = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "text/plain": "txt",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "text/csv": "csv",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
}

# Google Workspace native types → export target
_GOOGLE_APPS_EXPORT: dict[str, Tuple[str, str]] = {
    "application/vnd.google-apps.document": ("application/pdf", "pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    ),
    "application/vnd.google-apps.presentation": ("application/pdf", "pdf"),
    "application/vnd.google-apps.drawing": ("application/pdf", "pdf"),
}


@dataclass(frozen=True)
class DriveFileRef:
    id: str
    name: str
    mime_type: str


@dataclass
class DriveDownloadPlan:
    drive_file_id: str
    output_filename: str
    export_mime: Optional[str]  # None → get_media


def resolve_output_filename(name: str, mime_type: str) -> str:
    """Map Drive metadata to a safe on-disk filename with allowed extension."""
    base = sanitize_upload_filename(name)
    ext = file_extension(base)

    if mime_type in _GOOGLE_APPS_EXPORT:
        _, export_ext = _GOOGLE_APPS_EXPORT[mime_type]
        stem = base.rsplit(".", 1)[0] if ext else base
        return f"{stem}.{export_ext}"

    if not ext:
        guessed = _MIME_TO_EXT.get(mime_type)
        if guessed:
            stem = base.rsplit(".", 1)[0] if "." in base else base
            return f"{stem}.{guessed}"

    return base


def build_download_plan(file_ref: DriveFileRef) -> DriveDownloadPlan:
    filename = resolve_output_filename(file_ref.name, file_ref.mime_type)
    ext = file_extension(filename)
    if not is_allowed_extension(ext):
        allowed = ", ".join(e.lstrip(".") for e in config.ALLOWED_EXTENSIONS)
        raise ValueError(
            f"«{file_ref.name}» ({file_ref.mime_type}): неподдерживаемый тип после конвертации. "
            f"Допустимо: {allowed}"
        )

    if file_ref.mime_type in _GOOGLE_APPS_EXPORT:
        export_mime, _ = _GOOGLE_APPS_EXPORT[file_ref.mime_type]
        return DriveDownloadPlan(
            drive_file_id=file_ref.id,
            output_filename=filename,
            export_mime=export_mime,
        )

    return DriveDownloadPlan(
        drive_file_id=file_ref.id,
        output_filename=filename,
        export_mime=None,
    )


def _build_drive_service(access_token: str):
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google Drive import dependencies not installed "
            "(google-api-python-client, google-auth)"
        ) from exc

    creds = Credentials(token=access_token)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def download_drive_file_to_path(
    access_token: str,
    plan: DriveDownloadPlan,
    dest_path: str,
    *,
    chunk_size: int = 1024 * 1024,
) -> int:
    """
    Stream a Drive file (or export) to dest_path.
    Returns total bytes written.
    """
    service = _build_drive_service(access_token)

    if plan.export_mime:
        request = service.files().export_media(
            fileId=plan.drive_file_id,
            mimeType=plan.export_mime,
        )
    else:
        request = service.files().get_media(fileId=plan.drive_file_id)

    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise RuntimeError("google-api-python-client is required") from exc

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    total = 0
    with open(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_size)
        done = False
        while not done:
            _status, done = downloader.next_chunk()
        total = os.path.getsize(dest_path)

    if total > config.MAX_FILE_SIZE:
        try:
            os.remove(dest_path)
        except OSError:
            pass
        max_mb = config.MAX_FILE_SIZE / 1024 / 1024
        raise ValueError(f"Файл превышает лимит {max_mb:.0f} МБ после скачивания")

    if total == 0:
        try:
            os.remove(dest_path)
        except OSError:
            pass
        raise ValueError("Пустой файл после скачивания с Google Drive")

    return total

