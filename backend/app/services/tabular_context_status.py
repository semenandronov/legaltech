"""Failure taxonomy for tabular context / retrieval (observability contract)."""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

TabularContextOutcome = Literal[
    "empty_query",
    "no_recall_docs",
    "empty_context",
    "weak_coverage",
    "escalated",
    "front_matter_hit",
    "extract_na",
    "ok",
]


from app.services.tabular_extraction_policy import is_na_cell_value


def classify_tabular_context_outcome(
    *,
    meta: Optional[Dict[str, Any]] = None,
    context_text: str = "",
    recall_docs_count: int = 0,
    weak_coverage: bool = False,
    escalated: bool = False,
    cell_value: Optional[str] = None,
) -> TabularContextOutcome:
    m = meta or {}
    status = str(m.get("status") or "").strip()
    if status == "empty_query":
        return "empty_query"
    if status == "front_matter_hit":
        return "front_matter_hit"
    if status == "no_recall_docs" or recall_docs_count <= 0:
        if not context_text.strip():
            return "no_recall_docs"
    if not context_text.strip():
        return "empty_context"
    if weak_coverage or status == "weak_coverage":
        return "weak_coverage"
    if escalated or m.get("escalation_round", 0):
        return "escalated"
    if is_na_cell_value(cell_value):
        return "extract_na"
    return "ok"


def merge_context_meta(
    base: Optional[Dict[str, Any]],
    *,
    outcome: TabularContextOutcome,
    recall_pool_hit: Optional[bool] = None,
    prompt_hit: Optional[bool] = None,
    escalation_used: bool = False,
    navigation_context: str = "",
) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(base or {})
    out["context_outcome"] = outcome
    out["context_compiler_version"] = "tabular_context_compiler_v1"
    if recall_pool_hit is not None:
        out["recall_pool_hit"] = recall_pool_hit
    if prompt_hit is not None:
        out["prompt_hit"] = prompt_hit
    if escalation_used:
        out["escalation_used"] = True
    if navigation_context.strip():
        out["navigation_context"] = navigation_context[:1200]
    return out
