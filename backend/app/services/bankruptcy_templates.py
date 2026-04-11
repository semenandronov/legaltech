"""
Системные шаблоны документов по банкротству (файлы в app/templates/bankruptcy/).
"""
from __future__ import annotations

import json
import logging
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
        out.append(
            {
                "id": tid,
                "title": item.get("title", tid),
                "description": item.get("description", ""),
            }
        )
    return out


def get_template_meta(template_id: str) -> Optional[Dict[str, Any]]:
    for item in _load_manifest_raw():
        if isinstance(item, dict) and item.get("id") == template_id:
            return item
    return None


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
