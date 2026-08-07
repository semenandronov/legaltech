"""Conditional column run rules for Tabular Review.

``column_config.run_condition``:
{
  "source_column_id": "<uuid>",
  "operator": "equals|not_equals|is_yes|is_no|is_empty|is_not_empty|contains",
  "value": "optional for equals/not_equals/contains"
}
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

from app.services.tabular_extraction_policy import is_na_cell_value

CONDITION_OPERATORS = (
    "equals",
    "not_equals",
    "is_yes",
    "is_no",
    "is_empty",
    "is_not_empty",
    "contains",
)

YES_TOKENS = frozenset({"да", "yes", "true", "1", "y", "д"})
NO_TOKENS = frozenset({"нет", "no", "false", "0", "n", "н"})


@dataclass(frozen=True)
class RunCondition:
    source_column_id: str
    operator: str
    value: Optional[str] = None


def parse_run_condition(column_config: Optional[Dict[str, Any]]) -> Optional[RunCondition]:
    if not isinstance(column_config, dict):
        return None
    raw = column_config.get("run_condition")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("column_config.run_condition must be an object")
    source = str(raw.get("source_column_id") or "").strip()
    operator = str(raw.get("operator") or "").strip().lower()
    if not source:
        raise ValueError("run_condition.source_column_id is required")
    if operator not in CONDITION_OPERATORS:
        allowed = ", ".join(CONDITION_OPERATORS)
        raise ValueError(f"Invalid run_condition.operator '{operator}'. Allowed: {allowed}")
    value = raw.get("value")
    value_str = None if value is None else str(value)
    if operator in {"equals", "not_equals", "contains"} and (
        value_str is None or not str(value_str).strip()
    ):
        raise ValueError(f"run_condition.value is required for operator '{operator}'")
    return RunCondition(source_column_id=source, operator=operator, value=value_str)


def validate_run_condition_graph(
    *,
    column_id: Optional[str],
    column_config: Optional[Dict[str, Any]],
    review_column_ids: Set[str],
    conditions_by_column: Dict[str, Optional[RunCondition]],
) -> None:
    """Validate source exists and there is no dependency cycle."""
    condition = parse_run_condition(column_config)
    if condition is None:
        return
    if condition.source_column_id not in review_column_ids:
        raise ValueError(
            f"run_condition.source_column_id '{condition.source_column_id}' "
            "is not a column in this review"
        )
    if column_id and condition.source_column_id == column_id:
        raise ValueError("Column cannot depend on itself")

    # Detect cycles including the prospective edge.
    graph = {
        cid: (cond.source_column_id if cond else None)
        for cid, cond in conditions_by_column.items()
    }
    if column_id:
        graph[column_id] = condition.source_column_id

    def _has_cycle(start: str) -> bool:
        seen: Set[str] = set()
        cur: Optional[str] = start
        while cur:
            if cur in seen:
                return True
            seen.add(cur)
            cur = graph.get(cur)
        return False

    probe = column_id or condition.source_column_id
    if column_id and _has_cycle(column_id):
        raise ValueError("run_condition creates a dependency cycle between columns")
    if not column_id:
        # Creating new column: only need source not eventually pointing at a temp id.
        if _has_cycle(condition.source_column_id):
            raise ValueError("run_condition source column is part of a dependency cycle")


def _norm_token(value: Optional[str]) -> str:
    return (value or "").strip().lower().replace("ё", "е")


def _is_empty_value(value: Optional[str]) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    if is_na_cell_value(text):
        return True
    if text in {"—", "-", "–", "пропущено", "skipped"}:
        return True
    return False


def evaluate_run_condition(
    condition: RunCondition,
    *,
    source_cell_value: Optional[str],
    source_normalized_value: Optional[str] = None,
) -> bool:
    """Return True when the dependent column should run."""
    raw = source_cell_value
    norm = source_normalized_value if source_normalized_value is not None else raw
    token = _norm_token(norm if norm is not None else raw)
    op = condition.operator

    if op == "is_empty":
        return _is_empty_value(raw)
    if op == "is_not_empty":
        return not _is_empty_value(raw)
    if op == "is_yes":
        return token in YES_TOKENS
    if op == "is_no":
        return token in NO_TOKENS
    expected = _norm_token(condition.value)
    if op == "equals":
        return token == expected
    if op == "not_equals":
        return token != expected
    if op == "contains":
        return expected in token
    return False


def skipped_extraction_result(
    *,
    file_id: str,
    column_id: str,
    condition: RunCondition,
    source_label: str,
) -> Dict[str, Any]:
    return {
        "file_id": file_id,
        "column_id": column_id,
        "cell_value": None,
        "normalized_value": None,
        "verbatim_extract": None,
        "reasoning": (
            f"Пропущено: условие колонки не выполнено "
            f"(зависимость от «{source_label}», operator={condition.operator})."
        ),
        "source_references": [],
        "confidence_score": None,
        "status": "skipped",
        "extraction_method": "conditional_skip",
        "verified_flag": None,
        "user_flag": None,
    }
