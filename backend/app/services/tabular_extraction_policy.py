"""
Tabular extraction policy — evidence-first rules and shared normalizers.

Pure functions only; safe to import from pipeline, tests, and LangGraph nodes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from app.config import config
from app.models.tabular_review import TabularColumn

# Canonical stored / displayed value when the document has no suitable fragment.
TABULAR_NA_VALUE = "—"

DEFAULT_NA_REASONING = (
    "Чёткий ответ не сформирован: в доступных фрагментах документа не найден "
    "нужный участок текста, который подтверждал бы ответ на вопрос столбца."
)

# Column types where an unsupported answer without grounding is rejected (→ прочерк).
_FACT_COLUMN_TYPES: Set[str] = frozenset(
    {"date", "currency", "number", "yes_no", "tag", "verbatim"}
)

# All AI-filled types that must cite source material for non-NA values.
_EVIDENCE_REQUIRED_TYPES: Set[str] = frozenset(
    _FACT_COLUMN_TYPES | {"text"}
)

_NA_TOKENS: frozenset[str] = frozenset(
    {
        "",
        "N/A",
        "NA",
        "Н/Д",
        "НЕТ ДАННЫХ",
        "ОТСУТСТВУЕТ",
        "НЕ УКАЗАНО",
        "НЕ НАЙДЕНО",
        "NOT FOUND",
        "NONE",
    }
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


def is_explicit_na_token(value: Optional[str]) -> bool:
    """True for labeled not-found values (N/A, «—», legacy «Не найдено»), not hyphen blank."""
    if value is None:
        return False
    stripped = str(value).strip()
    if not stripped:
        return False
    if stripped == TABULAR_NA_VALUE:
        return True
    # Hyphen / en-dash alone = blank placeholder, not an explicit NA label.
    if stripped in ("-", "–"):
        return False
    return stripped.upper() in _NA_TOKENS


def canonicalize_na_cell_value(value: Optional[str]) -> str:
    """Map any NA token (legacy N/A / «Не найдено» included) to the canonical прочерк."""
    if is_na_cell_value(value):
        return TABULAR_NA_VALUE
    return str(value).strip()


def ensure_na_reasoning(
    reasoning: Optional[str],
    *,
    rejection: Optional[str] = None,
) -> str:
    """Guarantee a lawyer-facing explanation when the answer is a прочерк (not found)."""
    base = (reasoning or "").strip()
    if rejection:
        rejection_note = f"Значение отклонено: {rejection}."
        if base:
            return f"{rejection_note} {base}".strip()
        return f"{rejection_note} {DEFAULT_NA_REASONING}".strip()
    if base:
        return base
    return DEFAULT_NA_REASONING


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


def tabular_reasoning_max_chars() -> int:
    return max(40, int(getattr(config, "TABULAR_REASONING_MAX_CHARS", 160) or 160))


def tabular_ref_text_max_chars() -> int:
    return max(40, int(getattr(config, "TABULAR_REF_TEXT_MAX_CHARS", 220) or 220))


def tabular_max_source_refs() -> int:
    return max(1, int(getattr(config, "TABULAR_MAX_SOURCE_REFS", 1) or 1))


def tabular_verbatim_max_chars() -> int:
    return max(40, int(getattr(config, "TABULAR_VERBATIM_MAX_CHARS", 280) or 280))


def _truncate_words(text: str, *, max_chars: int) -> str:
    """Hard-cap citation/reasoning text without inventing content."""
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned or len(cleaned) <= max_chars:
        return cleaned
    clipped = cleaned[: max_chars].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip()
    return clipped


def compact_extraction_provenance(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Shrink LLM provenance fields that inflate output tokens / storage.

    Keeps one short grounded quote; caps reasoning. Does not invent citations.
    """
    out = dict(payload)
    reason_cap = tabular_reasoning_max_chars()
    ref_cap = tabular_ref_text_max_chars()
    verbatim_cap = tabular_verbatim_max_chars()
    max_refs = tabular_max_source_refs()

    reasoning = out.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        out["reasoning"] = _truncate_words(reasoning, max_chars=reason_cap)
    elif not reasoning:
        out["reasoning"] = "Извлечено из документа"

    verbatim = out.get("verbatim_extract")
    if isinstance(verbatim, str) and verbatim.strip():
        out["verbatim_extract"] = _truncate_words(verbatim, max_chars=verbatim_cap)

    refs = coerce_source_references(out.get("source_references"))
    compact_refs: List[Dict[str, Any]] = []
    for item in refs[:max_refs]:
        ref = dict(item)
        text = ref.get("text")
        if isinstance(text, str) and text.strip():
            ref["text"] = _truncate_words(text, max_chars=ref_cap)
        compact_refs.append(ref)
    # Prefer a single citation: if verbatim exists and refs empty, synthesize one short ref.
    if not compact_refs and isinstance(out.get("verbatim_extract"), str):
        quote = str(out.get("verbatim_extract") or "").strip()
        if quote:
            compact_refs = [{"text": quote}]
            page = out.get("source_page")
            section = out.get("source_section")
            if page is not None:
                compact_refs[0]["page"] = page
            if section:
                compact_refs[0]["section"] = section
    out["source_references"] = compact_refs
    return out


def count_nonempty_cells(cells: List[Dict[str, Any]]) -> int:
    """Cells with a user-visible answer (not прочерк / empty)."""
    n = 0
    for cell in cells:
        val = cell.get("cell_value")
        if not is_na_cell_value(val if val is None else str(val)):
            n += 1
    return n
