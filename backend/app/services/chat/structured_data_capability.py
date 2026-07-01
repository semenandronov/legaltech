"""
Capability invariants for SQL vs RAG routing — logic, not phrase lists.
"""
from __future__ import annotations

from app.services.chat.conversation_turn_state import InformationNeed

_TABULAR_NEEDS = frozenset({"tabular_aggregate", "tabular_list", "tabular_find"})
_DOCUMENT_NEEDS = frozenset({"document_narrative", "document_drill_down"})

TABULAR_INFORMATION_NEEDS = _TABULAR_NEEDS
DOCUMENT_INFORMATION_NEEDS = _DOCUMENT_NEEDS


def enforce_data_plane_capability(
    plane: str,
    information_need: InformationNeed,
    *,
    has_sql_tables: bool,
) -> tuple[str, str]:
    """
    Apply hard invariants after LLM router.

    Returns (plane, override_reason).
    """
    p = (plane or "rag").strip().lower()
    need = (information_need or "unknown").strip().lower()

    if need in _DOCUMENT_NEEDS and p == "sql":
        return "rag", f"capability_narrative_overrides_sql:{need}"

    if need in _TABULAR_NEEDS and p == "rag" and has_sql_tables:
        return "sql", f"capability_tabular_prefers_sql:{need}"

    if p == "sql" and not has_sql_tables:
        return "rag", "capability_no_sql_tables"

    return p, ""
