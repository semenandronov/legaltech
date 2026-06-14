"""
Системные шаблоны Draft (docxtpl DOCX + manifest.json).

Манифест: id, title, engine, file, variables[].
Вопросы для LLM — в bankruptcy_field_catalog.py (единый каталог).
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DIR = Path(__file__).resolve().parent.parent / "templates" / "draft"
_MANIFEST = _DIR / "manifest.json"

MAX_TEMPLATE_CHARS = 0


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


def clear_manifest_cache() -> None:
    _load_manifest_raw.cache_clear()


def get_template_meta(template_id: str) -> Optional[Dict[str, Any]]:
    for item in _load_manifest_raw():
        if isinstance(item, dict) and item.get("id") == template_id:
            return item
    return None


def get_template_engine(template_id: str) -> str:
    meta = get_template_meta(template_id)
    if not meta:
        return "html"
    return str(meta.get("engine") or "html").strip().lower()


def get_manifest_variables(template_id: str) -> List[str]:
    """Список переменных docxtpl из manifest."""
    meta = get_template_meta(template_id)
    if not meta:
        from app.services.bankruptcy_field_catalog import get_template_variables

        return get_template_variables(template_id)
    raw = meta.get("variables")
    if isinstance(raw, list) and raw:
        return [str(v).strip() for v in raw if v]
    return []


def get_manifest_placeholders(template_id: str) -> List[Dict[str, Any]]:
    """
    Обратная совместимость: для docxtpl возвращает placeholders из variables + каталог.
    Для html-шаблонов — placeholders из manifest.
    """
    if get_template_engine(template_id) == "docxtpl":
        from app.services.bankruptcy_field_catalog import docxtpl_marker, get_field_meta, get_field_description

        out: List[Dict[str, Any]] = []
        for var in get_manifest_variables(template_id):
            meta = get_field_meta(var)
            out.append(
                {
                    "variable": var,
                    "marker": docxtpl_marker(var),
                    "fill_question": get_field_description(var),
                    "entity_role": meta.get("entity_role"),
                    "data_type": meta.get("data_type", "other"),
                }
            )
        return out

    meta = get_template_meta(template_id)
    if not meta:
        return []
    raw = meta.get("placeholders")
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        marker = str(item.get("marker") or "").strip()
        fill_question = str(item.get("fill_question") or "").strip()
        if marker and fill_question:
            out.append(item)
    return out


def get_docx_path(template_id: str) -> Optional[Path]:
    meta = get_template_meta(template_id)
    if not meta:
        return None
    fname = meta.get("file")
    if not fname:
        return None
    path = _DIR / str(fname)
    return path if path.is_file() else None


def list_public_templates() -> List[Dict[str, Any]]:
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
                "engine": item.get("engine", "html"),
                "auto_matchable": has_file,
                "keyword_routable": keyword_mode,
            }
        )
    return out


def find_best_system_template_match(
    user_query: str,
    *,
    min_score: int = 8,
) -> Optional[str]:
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
    Загрузить тело шаблона для редактора.

    docxtpl: DOCX → preview HTML (с сохранением {{ variable }}).
    html: читает .html/.htm напрямую.
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
        engine = get_template_engine(template_id)
        if engine == "docxtpl" and path.suffix.lower() == ".docx":
            from app.services.draft_docxtpl_service import docx_to_preview_html

            return docx_to_preview_html(path), meta.get("title")
        if path.suffix.lower() == ".pdf":
            from app.services.document_converter_service import DocumentConverterService

            raw = path.read_bytes()
            conv = DocumentConverterService()
            text = conv.convert_to_html(raw, fname)
        else:
            text = path.read_text(encoding="utf-8")
        return text, meta.get("title")
    except Exception as e:
        logger.error("[bankruptcy_templates] read failed %s: %s", path, e)
        return None, meta.get("title")
