"""
Tabular extraction policy — evidence-first rules and shared normalizers.

Pure functions only; safe to import from pipeline, tests, and LangGraph nodes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from app.config import config
from app.models.tabular_review import TabularColumn

# Column types where an unsupported answer without grounding is rejected (→ N/A).
_FACT_COLUMN_TYPES: Set[str] = frozenset(
    {"date", "currency", "number", "yes_no", "tag", "document_type", "verbatim"}
)

# All AI-filled types that must cite source material for non-N/A values.
_EVIDENCE_REQUIRED_TYPES: Set[str] = frozenset(
    _FACT_COLUMN_TYPES | {"text"}
)

_NA_TOKENS: frozenset[str] = frozenset(
    {"", "N/A", "NA", "Н/Д", "НЕТ ДАННЫХ", "ОТСУТСТВУЕТ", "НЕ УКАЗАНО"}
)


def tabular_confidence_review_threshold() -> float:
    return float(getattr(config, "TABULAR_CONFIDENCE_REVIEW_THRESHOLD", 0.7) or 0.7)


def tabular_confidence_auto_complete_threshold() -> float:
    return float(getattr(config, "TABULAR_CONFIDENCE_AUTO_COMPLETE_THRESHOLD", 0.6) or 0.6)


def tabular_evidence_required_enabled() -> bool:
    return bool(getattr(config, "TABULAR_EVIDENCE_REQUIRED", True))


def is_na_cell_value(value: Optional[str]) -> bool:
    if value is None:
        return True
    stripped = str(value).strip()
    if not stripped:
        return True
    upper = stripped.upper()
    if upper in _NA_TOKENS:
        return True
    if stripped in ("—", "-", "–"):
        return True
    return False


def column_requires_evidence(column: TabularColumn) -> bool:
    if not tabular_evidence_required_enabled():
        return False
    if column.column_type == "manual_input":
        return False
    cfg = column.column_config if isinstance(column.column_config, dict) else {}
    if cfg.get("evidence_required") is False:
        return False
    if cfg.get("evidence_required") is True:
        return True
    return column.column_type in _EVIDENCE_REQUIRED_TYPES


def column_is_fact_type(column_type: str) -> bool:
    return column_type in _FACT_COLUMN_TYPES


def coerce_source_references(raw: Any) -> List[Dict[str, Any]]:
    """Normalize LLM source_references to a list of dicts."""
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        return [{"text": text}] if text else []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        out: List[Dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                out.append(item)
            elif isinstance(item, str) and item.strip():
                out.append({"text": item.strip()})
        return out
    return []


def count_nonempty_cells(cells: List[Dict[str, Any]]) -> int:
    """Cells with a user-visible answer (not N/A / empty)."""
    n = 0
    for cell in cells:
        val = cell.get("cell_value")
        if not is_na_cell_value(val if val is None else str(val)):
            n += 1
    return n
