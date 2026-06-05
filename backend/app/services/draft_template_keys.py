"""Ключи шаблонов Draft для единого каталога полей."""
from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models.document_template import DocumentTemplate
from app.services.bankruptcy_templates import get_template_meta
from app.services.draft_admin_template_service import ADMIN_DRAFT_SOURCE


def template_key_for_system_id(db: Optional[Session], template_system_id: str) -> Optional[str]:
    tid = (template_system_id or "").strip()
    if not tid:
        return None
    if get_template_meta(tid):
        return f"bankruptcy:{tid}"
    if db is not None:
        rec = db.query(DocumentTemplate).filter(DocumentTemplate.id == tid).first()
        if rec:
            return f"db:{tid}"
    return None


def template_key_for_db_template(template_id: str) -> str:
    return f"db:{template_id.strip()}"


def template_key_for_bankruptcy(manifest_id: str) -> str:
    return f"bankruptcy:{manifest_id.strip()}"


def parse_template_key(template_key: str) -> Tuple[str, str]:
    """Returns (source_kind, id) e.g. ('bankruptcy', 'rtk_claim_st71')."""
    key = (template_key or "").strip()
    if ":" in key:
        kind, ident = key.split(":", 1)
        return kind.strip(), ident.strip()
    return "unknown", key


def is_admin_db_template(db: Session, template_system_id: str) -> bool:
    rec = db.query(DocumentTemplate).filter(DocumentTemplate.id == template_system_id).first()
    return bool(rec and rec.source == ADMIN_DRAFT_SOURCE)
