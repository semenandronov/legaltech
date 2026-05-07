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


def _max_template_chars() -> int:
    from app.services.bankruptcy_templates import MAX_TEMPLATE_CHARS

    return MAX_TEMPLATE_CHARS


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
    cap = _max_template_chars()
    return (rec.content or "")[:cap], rec.title


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
    cap = _max_template_chars()
    if len(html) > cap:
        html = html[:cap]
        logger.warning("[draft_admin] template HTML truncated to %s chars", cap)

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
    return rec


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
