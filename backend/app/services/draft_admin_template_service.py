"""Админские шаблоны Draft: загрузка в document_templates, публичный каталог для ассистента."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import config
from app.models.document_template import DocumentTemplate
from app.models.user import User

logger = logging.getLogger(__name__)

ADMIN_DRAFT_SOURCE = "admin_draft"


def is_draft_template_admin(user: Optional[User]) -> bool:
    """Любой авторизованный пользователь может загружать общие шаблоны Draft."""
    return bool(user and getattr(user, "id", None))


def list_admin_template_catalog_entries(db: Session) -> List[Dict[str, str]]:
    rows = (
        db.query(DocumentTemplate)
        .filter(
            DocumentTemplate.source == ADMIN_DRAFT_SOURCE,
            DocumentTemplate.is_public.is_(True),
        )
        .order_by(DocumentTemplate.created_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "title": r.title or r.id,
            "description": (r.description or "")[:2000],
        }
        for r in rows
    ]


def list_merged_public_templates(db: Session) -> List[Dict[str, Any]]:
    from app.services.bankruptcy_templates import list_public_templates

    out: List[Dict[str, Any]] = list(list_public_templates())
    seen = {str(x["id"]) for x in out}
    for row in (
        db.query(DocumentTemplate)
        .filter(
            DocumentTemplate.source == ADMIN_DRAFT_SOURCE,
            DocumentTemplate.is_public.is_(True),
        )
        .order_by(DocumentTemplate.created_at.desc())
        .all()
    ):
        rid = str(row.id)
        if rid in seen:
            continue
        seen.add(rid)
        out.append(
            {
                "id": rid,
                "title": row.title,
                "description": row.description or "",
                "auto_matchable": True,
                "keyword_routable": False,
                "source": "admin",
            }
        )
    return out


def load_admin_draft_template_body(db: Session, template_id: str) -> Tuple[Optional[str], Optional[str]]:
    rec = (
        db.query(DocumentTemplate)
        .filter(
            DocumentTemplate.id == template_id,
            DocumentTemplate.source == ADMIN_DRAFT_SOURCE,
            DocumentTemplate.is_public.is_(True),
        )
        .first()
    )
    if not rec or not (rec.content or "").strip():
        return None, None
    return (rec.content or ""), rec.title


def _bytes_to_html(content: bytes, filename: str) -> str:
    _, dot, ext = filename.rpartition(".")
    ext_l = ext.lower() if dot else ""
    if ext_l in ("html", "htm"):
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("utf-8", errors="replace")
    from app.services.document_converter_service import DocumentConverterService

    conv = DocumentConverterService()
    return conv.convert_to_html(content, filename, file_type=ext_l or None)


def create_admin_draft_template(
    db: Session,
    user: User,
    file_content: bytes,
    filename: str,
    title: str,
    description: Optional[str] = None,
) -> DocumentTemplate:
    if not is_draft_template_admin(user):
        raise PermissionError("Требуется авторизация")
    if not file_content:
        raise ValueError("Пустой файл")
    max_sz = int(getattr(config, "MAX_FILE_SIZE", 60 * 1024 * 1024))
    if len(file_content) > max_sz:
        raise ValueError("Файл слишком большой")
    if not filename:
        raise ValueError("Не указано имя файла")
    _, dot, ext = filename.rpartition(".")
    if not dot:
        raise ValueError("Укажите файл с расширением")
    ext_l = ext.lower()
    allowed = {"pdf", "docx", "doc", "txt", "html", "htm", "rtf"}
    if ext_l not in allowed:
        raise ValueError(
            f"Неподдерживаемый формат .{ext_l}; допустимо: {', '.join(sorted(allowed))}"
        )

    html = _bytes_to_html(file_content, filename)

    ttitle = (title or "").strip() or filename.rsplit(".", 1)[0]
    rec = DocumentTemplate(
        id=str(uuid.uuid4()),
        source=ADMIN_DRAFT_SOURCE,
        source_doc_id=None,
        title=ttitle[:255],
        description=(description or "").strip() or None,
        content=html,
        is_public=True,
        is_system=True,
        user_id=user.id,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    logger.info("[draft_admin] created template id=%s title=%s", rec.id, rec.title)

    try:
        from app.config import config
        from app.services.draft_template_keys import template_key_for_db_template
        from app.services.draft_template_indexer import index_template_html

        if bool(getattr(config, "DRAFT_TEMPLATE_INDEX_ON_UPLOAD", True)):
            tkey = template_key_for_db_template(str(rec.id))
            snap, status = index_template_html(
                db,
                template_key=tkey,
                html=html,
                template_title=ttitle,
                force=True,
            )
            logger.info(
                "[draft_admin] indexed template id=%s key=%s status=%s fields=%s",
                rec.id,
                tkey,
                status,
                len(snap.field_specs),
            )
    except Exception as idx_err:
        logger.warning("[draft_admin] template field index failed id=%s: %s", rec.id, idx_err)

    return rec


def reindex_admin_draft_template(db: Session, user: User, template_id: str) -> Dict[str, Any]:
    if not is_draft_template_admin(user):
        raise PermissionError("Требуется авторизация")
    rec = db.query(DocumentTemplate).filter(DocumentTemplate.id == template_id).first()
    if not rec or rec.source != ADMIN_DRAFT_SOURCE:
        raise ValueError("Шаблон не найден")
    from app.services.draft_template_keys import template_key_for_db_template
    from app.services.draft_template_indexer import index_template_html

    tkey = template_key_for_db_template(str(rec.id))
    snap, status = index_template_html(
        db,
        template_key=tkey,
        html=rec.content or "",
        template_title=rec.title,
        force=True,
    )
    return {
        "template_key": tkey,
        "index_status": status,
        "fields_count": len(snap.field_specs),
        "indexer_version": snap.indexer_version,
    }


def get_admin_template_fields(db: Session, template_id: str) -> Dict[str, Any]:
    from app.services.draft_template_catalog import load_catalog_snapshot
    from app.services.draft_template_keys import template_key_for_db_template

    tkey = template_key_for_db_template(template_id)
    snap = load_catalog_snapshot(db, tkey)
    if not snap:
        return {"template_key": tkey, "fields": [], "indexed_html_length": 0}
    return {
        "template_key": tkey,
        "fields": [s.model_dump() for s in snap.field_specs],
        "indexed_html_length": len(snap.indexed_html or ""),
        "content_sha256": snap.content_sha256,
    }


def delete_admin_draft_template(db: Session, user: User, template_id: str) -> bool:
    if not is_draft_template_admin(user):
        raise PermissionError("Требуется авторизация")
    rec = (
        db.query(DocumentTemplate)
        .filter(
            DocumentTemplate.id == template_id,
            DocumentTemplate.source == ADMIN_DRAFT_SOURCE,
        )
        .first()
    )
    if not rec:
        return False
    try:
        from app.services.draft_template_catalog import delete_catalog
        from app.services.draft_template_keys import template_key_for_db_template

        delete_catalog(db, template_key_for_db_template(template_id))
    except Exception as e:
        logger.warning("[draft_admin] catalog delete failed: %s", e)
    db.delete(rec)
    db.commit()
    return True


def list_admin_templates_for_management(db: Session) -> List[Dict[str, Any]]:
    rows = (
        db.query(DocumentTemplate)
        .filter(DocumentTemplate.source == ADMIN_DRAFT_SOURCE)
        .order_by(DocumentTemplate.created_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "title": r.title,
            "description": r.description or "",
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "content_length": len(r.content or ""),
        }
        for r in rows
    ]
