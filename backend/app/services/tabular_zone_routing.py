"""
Resolve preferred document zones for a tabular column (phase 2.3).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.document_zones import DOCUMENT_ZONE_SET, normalize_zone

# Defaults by column_type — soft preference, never a hard filter.
_DEFAULT_ZONES_BY_TYPE: Dict[str, Tuple[str, ...]] = {
    "date": ("preamble", "body"),
    "currency": ("body", "table", "requisites"),
    "number": ("body", "table", "requisites"),
    "yes_no": ("body", "preamble"),
    "verbatim": ("body", "preamble"),
    "text": ("body", "preamble"),
    "tag": ("body", "preamble"),
}

_PROMPT_ZONE_HINTS: Tuple[Tuple[re.Pattern[str], Tuple[str, ...]], ...] = (
    (
        re.compile(r"(?i)инн|кпп|огрн|реквизит|бик|р/?с\b|банк"),
        ("requisites", "preamble"),
    ),
    (
        re.compile(r"(?i)сторон\w*|арендодател|арендатор|поставщик|покупател|заказчик|исполнител"),
        ("preamble", "requisites"),
    ),
    (
        re.compile(r"(?i)дата\s+(?:договор|документ|соглашен)|дата\s+подписан"),
        ("preamble", "signature"),
    ),
    (
        re.compile(r"(?i)таблиц|график\s+платеж|спецификац|перечень"),
        ("table", "body"),
    ),
    (
        re.compile(r"(?i)подпис|м\.?\s*п\.?|печать"),
        ("signature", "preamble"),
    ),
    (
        re.compile(r"(?i)неустойк|штраф|ответственност|расторжен|предмет\s+договор"),
        ("body",),
    ),
)


def _clean_zone_list(values: Sequence[Any]) -> Tuple[str, ...]:
    out: List[str] = []
    seen = set()
    for raw in values:
        z = normalize_zone(raw)
        if not z or z == "full_document" or z in seen:
            continue
        if z not in DOCUMENT_ZONE_SET:
            continue
        seen.add(z)
        out.append(z)
    return tuple(out)


def preferred_zones_from_column_config(
    column_config: Optional[Dict[str, Any]],
) -> Tuple[str, ...]:
    if not isinstance(column_config, dict):
        return ()
    raw = column_config.get("preferred_zones")
    if isinstance(raw, str):
        raw = [p.strip() for p in raw.split(",") if p.strip()]
    if not isinstance(raw, (list, tuple)):
        return ()
    return _clean_zone_list(raw)


def infer_preferred_zones(
    *,
    column_type: str = "text",
    column_label: str = "",
    prompt: str = "",
    column_config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, ...]:
    """
    Explicit column_config.preferred_zones wins; else prompt heuristics + type defaults.
    """
    explicit = preferred_zones_from_column_config(column_config)
    if explicit:
        return explicit

    blob = f"{column_label or ''} {prompt or ''}".strip()
    for pattern, zones in _PROMPT_ZONE_HINTS:
        if blob and pattern.search(blob):
            return zones

    ctype = (column_type or "text").strip().lower()
    return _DEFAULT_ZONES_BY_TYPE.get(ctype, ("body", "preamble"))


def resolve_preferred_zones_for_column(column: Any) -> Tuple[str, ...]:
    cfg = getattr(column, "column_config", None)
    return infer_preferred_zones(
        column_type=str(getattr(column, "column_type", None) or "text"),
        column_label=str(getattr(column, "column_label", None) or ""),
        prompt=str(getattr(column, "prompt", None) or ""),
        column_config=cfg if isinstance(cfg, dict) else None,
    )
