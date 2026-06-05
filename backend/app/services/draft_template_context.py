"""
Единая сборка текста шаблона для draft:

1) явный template_system_id
2) template_file_content (вложение)
3) template_file_id (файл дела в БД)
4) автоподбор системного шаблона по запросу (LLM или keywords — см. DRAFT_TEMPLATE_SELECTION_MODE)
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.services.bankruptcy_templates import find_best_system_template_match, load_system_template_body
from app.services.draft_template_keys import template_key_for_system_id

logger = logging.getLogger(__name__)


def _load_template_body_unified(db: Session, template_id: str) -> Tuple[Optional[str], Optional[str]]:
    text, title = load_system_template_body(template_id.strip())
    if text:
        return text, title
    from app.services.draft_admin_template_service import load_admin_draft_template_body

    return load_admin_draft_template_body(db, template_id.strip())


def auto_pick_system_template_id(user_question: str, db: Optional[Session] = None) -> Optional[str]:
    """
    Выбор id системного шаблона по запросу пользователя (без явного template_system_id).

    Режимы config.DRAFT_TEMPLATE_SELECTION_MODE:
    - llm: классификация через LLM (каталог id/title/description из manifest)
    - keywords: прежний матчинг по intent_keywords
    - none / off: отключено
    """
    q = (user_question or "").strip()
    if len(q) < 2:
        return None

    try:
        from app.config import config

        mode = (getattr(config, "DRAFT_TEMPLATE_SELECTION_MODE", "llm") or "llm").strip().lower()
        min_score = int(getattr(config, "DRAFT_AUTO_TEMPLATE_MIN_SCORE", 8) or 8)
    except Exception:
        mode = "llm"
        min_score = 8

    if mode in ("none", "off", "false", "0"):
        return None

    if mode == "keywords":
        return find_best_system_template_match(q, min_score=min_score)

    if mode != "llm":
        logger.warning("[draft_template_context] unknown DRAFT_TEMPLATE_SELECTION_MODE=%s, using llm", mode)

    from app.services.draft_template_llm_select import select_system_template_id_via_llm

    return select_system_template_id_via_llm(q, db)

# Лимит снят: пользовательские/файловые шаблоны передаются целиком,
# чтобы не ломать структуру HTML. Оставлено как 0 для обратной совместимости.
MAX_USER_TEMPLATE_CHARS = 0  # 0 = без ограничения


def resolve_draft_template_context(
    db: Session,
    *,
    template_system_id: Optional[str] = None,
    template_file_content: Optional[str] = None,
    template_file_id: Optional[str] = None,
    user_question: Optional[str] = None,
    auto_match_system_template: bool = True,
) -> Tuple[str, Optional[str]]:
    """
    Returns:
        (template_text, label) — label для логов/UI; может быть None.
    Приоритет: template_system_id > template_file_content > template_file_id >
               автоподбор по user_question (если включён).
    """
    if template_system_id:
        tid = template_system_id.strip()
        text, title = _load_template_body_unified(db, tid)
        if text:
            tkey = template_key_for_system_id(db, tid)
            logger.info(
                "[draft_template_context] using system template id=%s title=%s key=%s",
                template_system_id,
                title,
                tkey,
            )
            return text, title, tkey
        logger.warning(
            "[draft_template_context] system template not found or empty: %s",
            template_system_id,
        )

    if template_file_content and str(template_file_content).strip():
        raw = str(template_file_content).strip()
        return raw, None, None

    if template_file_id:
        try:
            from app.models.case import File as FileModel

            rec = db.query(FileModel).filter(FileModel.id == template_file_id).first()
            if rec and rec.original_text:
                return rec.original_text, rec.filename or None, None
        except Exception as e:
            logger.warning("[draft_template_context] DB template load failed: %s", e)

    try:
        from app.config import config

        auto_on = bool(getattr(config, "DRAFT_AUTO_SYSTEM_TEMPLATE_MATCH", True))
    except Exception:
        auto_on = True

    if (
        auto_on
        and auto_match_system_template
        and user_question
        and str(user_question).strip()
    ):
        matched_id = auto_pick_system_template_id(user_question.strip(), db)
        if matched_id:
            text, title = _load_template_body_unified(db, matched_id)
            if text:
                logger.info(
                    "[draft_template_context] auto-selected system template id=%s title=%s",
                    matched_id,
                    title,
                )
                tkey = template_key_for_system_id(db, matched_id)
                return text, title, tkey

    return "", None, None
