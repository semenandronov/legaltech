"""
Auto-catalogizer for DD case intake.

After rules classification:
1) map doc type → lawyer data-room folder (not 1:1 with type);
2) ensure that system folder exists;
3) place the file there (unless user already filed it elsewhere);
4) rename only generic dump names (Scan_1 / Безымянный), keeping original in progress.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.services.dd_data_room import (
    DD_DATA_ROOM_BUCKETS,
    DD_LEGACY_TYPE_MARKER_PREFIX,
    data_room_bucket_label,
    dd_room_folder_marker,
    is_dd_system_folder_description,
    parse_dd_room_folder_marker,
    resolve_data_room_bucket,
)
from app.services.dd_document_classifier import (
    DdClassificationResult,
    filename_looks_generic,
)
from app.services.dd_document_taxonomy import dd_doc_type_label

logger = logging.getLogger(__name__)

_TITLE_CLEAN_RE = re.compile(r"\s+")
_UNSAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def dd_auto_catalog_enabled() -> bool:
    try:
        from app.config import config

        return bool(getattr(config, "DD_AUTO_CATALOG_ENABLED", True))
    except Exception:
        return True


def dd_auto_rename_enabled() -> bool:
    try:
        from app.config import config

        return bool(getattr(config, "DD_AUTO_RENAME_ENABLED", True))
    except Exception:
        return True


def _folder_is_auto_catalog(folder) -> bool:
    return is_dd_system_folder_description(getattr(folder, "description", None))


def ensure_dd_data_room_folder(db: Session, *, case_id: str, bucket_id: str):
    """Get or create the system data-room folder for a bucket."""
    from app.models.folder import Folder

    if bucket_id not in DD_DATA_ROOM_BUCKETS:
        bucket_id = "inbox"

    marker = dd_room_folder_marker(bucket_id)
    existing = (
        db.query(Folder)
        .filter(Folder.case_id == case_id, Folder.description == marker)
        .first()
    )
    if existing:
        return existing

    label = data_room_bucket_label(bucket_id)
    name = label
    clash = (
        db.query(Folder)
        .filter(
            Folder.case_id == case_id,
            Folder.parent_id.is_(None),
            Folder.name == name,
        )
        .first()
    )
    if clash and parse_dd_room_folder_marker(clash.description) != bucket_id:
        name = f"{label} (авто)"

    # Prefer stable order among data-room folders.
    try:
        order_index = DD_DATA_ROOM_BUCKETS.index(bucket_id)
    except ValueError:
        order_index = (
            db.query(Folder)
            .filter(Folder.case_id == case_id, Folder.parent_id.is_(None))
            .count()
        )

    folder = Folder(
        case_id=case_id,
        parent_id=None,
        name=name,
        description=marker,
        icon="dd_catalog",
        color=None,
        order_index=order_index,
        file_count=0,
    )
    db.add(folder)
    db.flush()
    return folder


# Back-compat alias used by older call sites / tests.
def ensure_dd_catalog_folder(db: Session, *, case_id: str, doc_type: str):
    bucket = resolve_data_room_bucket(doc_type)
    return ensure_dd_data_room_folder(db, case_id=case_id, bucket_id=bucket)


def _extract_title_snippet(text: str, *, max_len: int = 72) -> str:
    raw = _TITLE_CLEAN_RE.sub(" ", (text or "").strip())
    if not raw:
        return ""
    lower = raw.lower().replace("ё", "е")
    for anchor in ("договор", "дополнительное соглашение", "приложение", "претензия"):
        idx = lower.find(anchor)
        if idx >= 0:
            snippet = raw[idx : idx + max_len].strip(" .,;:\n\t")
            return snippet
    return raw[:max_len].strip(" .,;:\n\t")


def build_catalog_filename(
    *,
    doc_type: str,
    text: str,
    original_filename: str,
) -> str:
    """Human-readable name: «Аренда — Договор аренды … .pdf»."""
    import os

    ext = os.path.splitext(original_filename or "")[1] or ".pdf"
    if not ext.startswith("."):
        ext = f".{ext}"
    label = dd_doc_type_label(doc_type, short=True)
    snippet = _extract_title_snippet(text)
    if snippet:
        low = snippet.lower().replace("ё", "е")
        if low.startswith(label.lower()):
            base = snippet
        else:
            base = f"{label} — {snippet}"
    else:
        base = label
    base = _UNSAFE_NAME_RE.sub(" ", base)
    base = _TITLE_CLEAN_RE.sub(" ", base).strip(" .")
    if len(base) > 120:
        base = base[:117].rstrip() + "…"
    if not base:
        base = label or "Документ"
    return f"{base}{ext}"


def _bump_folder_counts(
    db: Session, *, old_folder_id: Optional[str], new_folder_id: Optional[str]
) -> None:
    from app.models.folder import Folder

    if old_folder_id and old_folder_id != new_folder_id:
        old = db.query(Folder).filter(Folder.id == old_folder_id).first()
        if old and (old.file_count or 0) > 0:
            old.file_count = int(old.file_count) - 1
    if new_folder_id and new_folder_id != old_folder_id:
        new = db.query(Folder).filter(Folder.id == new_folder_id).first()
        if new:
            new.file_count = int(new.file_count or 0) + 1


def apply_dd_auto_catalog(
    db: Session,
    file_model: Any,
    *,
    classification: DdClassificationResult,
    text: str,
    rename_generic_only: bool = True,
) -> dict:
    """
    Place file into a lawyer data-room folder and optionally rename.

    Never moves a file out of a *user* folder. May move from root or from a
    previous system folder (incl. legacy per-type folders) when mapping changes.
    """
    if not dd_auto_catalog_enabled():
        return {"skipped": True, "reason": "disabled"}

    case_id = str(getattr(file_model, "case_id", "") or "")
    if not case_id:
        return {"skipped": True, "reason": "no_case"}

    filename = str(getattr(file_model, "filename", "") or "")
    doc_type = str(classification.doc_type or "unknown").strip() or "unknown"
    bucket_id = resolve_data_room_bucket(
        doc_type,
        filename=filename,
        text=text or "",
    )

    from app.models.folder import Folder

    current_folder_id = getattr(file_model, "folder_id", None)
    current_folder = None
    if current_folder_id:
        current_folder = db.query(Folder).filter(Folder.id == current_folder_id).first()

    if current_folder and not _folder_is_auto_catalog(current_folder):
        catalog = {
            "folder_skipped": True,
            "reason": "user_folder",
            "bucket_id": bucket_id,
            "doc_type": doc_type,
        }
    else:
        target = ensure_dd_data_room_folder(db, case_id=case_id, bucket_id=bucket_id)
        old_id = current_folder_id
        if old_id != target.id:
            file_model.folder_id = target.id
            _bump_folder_counts(db, old_folder_id=old_id, new_folder_id=target.id)
        catalog = {
            "folder_id": target.id,
            "folder_name": target.name,
            "bucket_id": bucket_id,
            "doc_type": doc_type,
        }

    rename_info: dict = {"renamed": False}
    if dd_auto_rename_enabled():
        original = filename
        should_rename = (not rename_generic_only) or filename_looks_generic(original)
        progress = getattr(file_model, "processing_progress", None)
        if isinstance(progress, dict) and progress.get("dd_catalog", {}).get("original_filename"):
            should_rename = filename_looks_generic(original)

        if should_rename:
            new_name = build_catalog_filename(
                doc_type=doc_type,
                text=text,
                original_filename=original,
            )
            if new_name and new_name != original:
                progress = dict(progress) if isinstance(progress, dict) else {}
                catalog_meta = dict(progress.get("dd_catalog") or {})
                catalog_meta.setdefault("original_filename", original)
                catalog_meta["renamed_to"] = new_name
                catalog_meta["doc_type"] = doc_type
                catalog_meta["bucket_id"] = bucket_id
                progress["dd_catalog"] = catalog_meta
                file_model.processing_progress = progress
                file_model.filename = new_name
                rename_info = {
                    "renamed": True,
                    "from": original,
                    "to": new_name,
                }

    logger.info(
        "DD auto-catalog file=%s type=%s bucket=%s folder=%s rename=%s",
        getattr(file_model, "id", None),
        doc_type,
        bucket_id,
        catalog.get("folder_name") or catalog.get("reason"),
        rename_info,
    )
    return {"catalog": catalog, "rename": rename_info}


def prune_empty_legacy_dd_auto_folders(db: Session, *, case_id: str) -> int:
    """
    Remove empty legacy ``dd_auto:<type>`` folders after migration to data-room.

    Keeps ``dd_room:*`` folders even when empty (stable lawyer structure).
    """
    from app.models.case import File as FileModel
    from app.models.folder import Folder

    legacy = (
        db.query(Folder)
        .filter(
            Folder.case_id == case_id,
            Folder.description.startswith(DD_LEGACY_TYPE_MARKER_PREFIX),
        )
        .all()
    )
    removed = 0
    for folder in legacy:
        if int(folder.file_count or 0) > 0:
            continue
        # Double-check: no files still pointing here (count can drift).
        still = (
            db.query(FileModel)
            .filter(FileModel.case_id == case_id, FileModel.folder_id == folder.id)
            .count()
        )
        if still:
            folder.file_count = still
            continue
        db.delete(folder)
        removed += 1
    if removed:
        db.flush()
        logger.info("Pruned %s empty legacy DD auto folders case=%s", removed, case_id)
    return removed
