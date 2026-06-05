"""Load raw bytes for case File rows: disk (UPLOAD_DIR) first, DB fallback for legacy rows."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

from app.config import config

if TYPE_CHECKING:
    from app.models.case import File

logger = logging.getLogger(__name__)


def case_file_disk_path(file: "File") -> Optional[str]:
    """Absolute path to on-disk original, or None if missing / not configured."""
    fp = (file.file_path or "").strip()
    if not fp:
        return None
    if os.path.isabs(fp):
        return fp if os.path.isfile(fp) else None
    full = os.path.join(config.UPLOAD_DIR, fp)
    return full if os.path.isfile(full) else None


def load_case_file_bytes(file: "File") -> Optional[bytes]:
    """Read original file bytes for OCR/indexing and preview fallbacks."""
    path = case_file_disk_path(file)
    if path:
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as e:
            logger.warning(
                "Failed to read case file from disk path=%s file_id=%s: %s",
                path,
                getattr(file, "id", None),
                e,
            )
    if file.file_content:
        return bytes(file.file_content)
    return None


def case_file_content_for_db(content: bytes) -> Optional[bytes]:
    """Whether to persist raw bytes in Postgres on upload (legacy / split containers)."""
    if config.FILE_STORE_BYTES_IN_DB:
        return content
    return None
