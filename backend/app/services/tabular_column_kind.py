"""
Tabular ColumnKind router (phase 4).

Kinds control cost/latency of a cell:
- fact / verbatim → schema-first + light RAG
- summary → RAG with fuller context
- risk_analysis → fixed multi-step graph (not a free agent)
- manual → no AI
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from app.services.contract_field_catalog import field_id_from_column_config

COLUMN_KINDS: Tuple[str, ...] = (
    "fact",
    "verbatim",
    "summary",
    "risk_analysis",
    "manual",
)

COLUMN_KIND_SET = frozenset(COLUMN_KINDS)

_RISK_PROMPT_RE = re.compile(
    r"(?i)риск|risk|неблагоприят|красн\w*\s+флаг|red\s*flag|"
    r"проблемн|уязвим|перечисл\w*\s+риск|ключев\w*\s+риск|"
    r"material\s+adverse|carve[- ]?out"
)
_SUMMARY_PROMPT_RE = re.compile(
    r"(?i)кратко\s+опиши|суммирую|summary|резюм|overview|"
    r"основн\w*\s+условий|ключев\w*\s+положен"
)


def normalize_column_kind(raw: Any) -> Optional[str]:
    kind = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if kind in {"risk", "risks", "risks_analysis"}:
        kind = "risk_analysis"
    if kind in COLUMN_KIND_SET:
        return kind
    return None


def column_kind_from_config(column_config: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(column_config, dict):
        return None
    return normalize_column_kind(column_config.get("column_kind"))


def infer_column_kind(
    *,
    column_type: str = "text",
    column_label: str = "",
    prompt: str = "",
    column_config: Optional[Dict[str, Any]] = None,
) -> str:
    """Explicit config wins; else heuristics. Default is fact."""
    explicit = column_kind_from_config(column_config)
    if explicit:
        return explicit

    ctype = (column_type or "text").strip().lower()
    if ctype == "manual_input":
        return "manual"
    if ctype == "verbatim":
        return "verbatim"

    if field_id_from_column_config(column_config):
        return "fact"

    blob = f"{column_label or ''} {prompt or ''}"
    if _RISK_PROMPT_RE.search(blob):
        return "risk_analysis"
    if _SUMMARY_PROMPT_RE.search(blob):
        return "summary"
    return "fact"


def resolve_column_kind(column: Any) -> str:
    cfg = getattr(column, "column_config", None)
    return infer_column_kind(
        column_type=str(getattr(column, "column_type", None) or "text"),
        column_label=str(getattr(column, "column_label", None) or ""),
        prompt=str(getattr(column, "prompt", None) or ""),
        column_config=cfg if isinstance(cfg, dict) else None,
    )
