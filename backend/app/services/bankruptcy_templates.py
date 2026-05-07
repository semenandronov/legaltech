"""
Системные шаблоны документов (файлы в app/templates/bankruptcy/).

Манифест: id, title, description, file; опционально intent_keywords для режима
DRAFT_TEMPLATE_SELECTION_MODE=keywords. Режим llm (по умолчанию) передаёт все шаблоны с file в LLM.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DIR = Path(__file__).resolve().parent.parent / "templates" / "bankruptcy"
_MANIFEST = _DIR / "manifest.json"

# Максимальная длина текста шаблона, отдаваемого в LLM (символы)
MAX_TEMPLATE_CHARS = 32000


@lru_cache(maxsize=1)
def _load_manifest_raw() -> List[Dict[str, Any]]:
    if not _MANIFEST.is_file():
        logger.warning("[bankruptcy_templates] manifest not found: %s", _MANIFEST)
        return []
    try:
        data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error("[bankruptcy_templates] failed to load manifest: %s", e)
        return []


def list_public_templates() -> List[Dict[str, Any]]:
    """Список шаблонов для API (без путей к файлам на диске)."""
    out: List[Dict[str, Any]] = []
    for item in _load_manifest_raw():
        if not isinstance(item, dict):
            continue
        tid = item.get("id")
        if not tid:
            continue
        has_file = bool(item.get("file"))
        kws = item.get("intent_keywords")
        keyword_mode = bool(isinstance(kws, list) and len(kws) > 0)
        out.append(
            {
                "id": tid,
                "title": item.get("title", tid),
                "description": item.get("description", ""),
                "auto_matchable": has_file,
                "keyword_routable": keyword_mode,
            }
        )
    return out


def get_template_meta(template_id: str) -> Optional[Dict[str, Any]]:
    for item in _load_manifest_raw():
        if isinstance(item, dict) and item.get("id") == template_id:
            return item
    return None


def find_best_system_template_match(
    user_query: str,
    *,
    min_score: int = 8,
) -> Optional[str]:
    """
    Детерминированный выбор id шаблона по тексту запроса (Draft).

    Скоринг: сумма длин совпавших intent_keywords (подстрока в нормализованном запросе).
    При равном score побеждает больший priority из манифеста.

    Шаблоны без intent_keywords в манифесте не участвуют в автоподборе.
    """
    if not user_query or not str(user_query).strip():
        return None
    q = str(user_query).lower().strip()
    q = re.sub(r"\s+", " ", q)
    if len(q) < 3:
        return None

    best_id: Optional[str] = None
    best_score = 0
    best_priority = -10_000

    for item in _load_manifest_raw():
        if not isinstance(item, dict):
            continue
        tid = item.get("id")
        if not tid:
            continue
        kws = item.get("intent_keywords")
        if not isinstance(kws, list) or not kws:
            continue

        score = 0
        for kw in sorted((str(k).strip() for k in kws if k), key=len, reverse=True):
            kl = kw.lower().strip()
            if len(kl) < 2:
                continue
            if kl not in q:
                continue
            # Короткие токены не усиливают score, если в шаблоне много ключей (избегаем шума «иск»).
            if len(kl) < 4 and len(kws) > 1:
                continue
            score += len(kl)

        if score <= 0:
            continue

        pri = 0
        try:
            pri = int(item.get("priority") or 0)
        except (TypeError, ValueError):
            pri = 0

        if score > best_score or (score == best_score and pri > best_priority):
            best_score = score
            best_id = str(tid)
            best_priority = pri

    if best_id is None or best_score < min_score:
        return None
    logger.info(
        "[bankruptcy_templates] auto-matched template id=%s score=%s (min=%s)",
        best_id,
        best_score,
        min_score,
    )
    return best_id


def load_system_template_body(template_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Загрузить текст шаблона по id из манифеста.

    Returns:
        (text, title) или (None, None) если не найдено / ошибка чтения.
    """
    meta = get_template_meta(template_id)
    if not meta:
        return None, None
    fname = meta.get("file")
    if not fname or not isinstance(fname, str):
        return None, meta.get("title")
    path = _DIR / fname
    if not path.is_file():
        logger.error("[bankruptcy_templates] template file missing: %s", path)
        return None, meta.get("title")
    try:
        if path.suffix.lower() == ".pdf":
            from app.services.document_converter_service import DocumentConverterService

            raw = path.read_bytes()
            conv = DocumentConverterService()
            text = conv.convert_to_html(raw, fname)
        else:
            text = path.read_text(encoding="utf-8")
        if len(text) > MAX_TEMPLATE_CHARS:
            text = text[:MAX_TEMPLATE_CHARS]
        return text, meta.get("title")
    except Exception as e:
        logger.error("[bankruptcy_templates] read failed %s: %s", path, e)
        return None, meta.get("title")
