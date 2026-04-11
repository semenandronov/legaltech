"""
Единая сборка текста шаблона для draft: системный id > вложенный контент > файл из БД.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.services.bankruptcy_templates import load_system_template_body

logger = logging.getLogger(__name__)

# Совместимо с прежним лимитом DraftHandler; при необходимости поднять
MAX_USER_TEMPLATE_CHARS = 32000


def resolve_draft_template_context(
    db: Session,
    *,
    template_system_id: Optional[str] = None,
    template_file_content: Optional[str] = None,
    template_file_id: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """
    Returns:
        (template_text, label) — label для логов/UI; может быть None.
    Приоритет: template_system_id > template_file_content > template_file_id.
    """
    if template_system_id:
        text, title = load_system_template_body(template_system_id.strip())
        if text:
            logger.info(
                "[draft_template_context] using system template id=%s title=%s",
                template_system_id,
                title,
            )
            return text, title
        logger.warning(
            "[draft_template_context] system template not found or empty: %s",
            template_system_id,
        )

    if template_file_content and str(template_file_content).strip():
        raw = str(template_file_content).strip()
        return raw[:MAX_USER_TEMPLATE_CHARS], None

    if template_file_id:
        try:
            from app.models.case import File as FileModel

            rec = db.query(FileModel).filter(FileModel.id == template_file_id).first()
            if rec and rec.original_text:
                t = rec.original_text[:MAX_USER_TEMPLATE_CHARS]
                return t, rec.filename or None
        except Exception as e:
            logger.warning("[draft_template_context] DB template load failed: %s", e)

    return "", None
