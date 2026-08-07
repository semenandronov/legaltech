"""Multi-color user flags for Tabular Review cells.

Persisted on ``TabularCell.user_flag``: red | orange | yellow | green | null.

Optional auto-rules in ``column_config.flag_rules``:
[
  {"match": {"operator": "is_yes"}, "flag": "red"},
  {"match": {"operator": "contains", "value": "без уведомления"}, "flag": "orange"}
]
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.tabular_column_condition import (
    CONDITION_OPERATORS,
    RunCondition,
    evaluate_run_condition,
)

USER_FLAG_COLORS = ("red", "orange", "yellow", "green")


def normalize_user_flag(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in {"none", "null", "clear", "-"}:
        return None
    if text not in USER_FLAG_COLORS:
        allowed = ", ".join(USER_FLAG_COLORS)
        raise ValueError(f"Invalid user_flag '{value}'. Allowed: {allowed}")
    return text


def parse_flag_rules(column_config: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(column_config, dict):
        return []
    raw = column_config.get("flag_rules")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("column_config.flag_rules must be a list")
    rules: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"flag_rules[{idx}] must be an object")
        flag = normalize_user_flag(item.get("flag"))
        if flag is None:
            raise ValueError(f"flag_rules[{idx}].flag is required")
        match = item.get("match")
        if not isinstance(match, dict):
            raise ValueError(f"flag_rules[{idx}].match must be an object")
        operator = str(match.get("operator") or "").strip().lower()
        if operator not in CONDITION_OPERATORS:
            allowed = ", ".join(CONDITION_OPERATORS)
            raise ValueError(
                f"Invalid flag_rules[{idx}].match.operator '{operator}'. Allowed: {allowed}"
            )
        value = match.get("value")
        value_str = None if value is None else str(value)
        if operator in {"equals", "not_equals", "contains"} and (
            value_str is None or not str(value_str).strip()
        ):
            raise ValueError(
                f"flag_rules[{idx}].match.value is required for operator '{operator}'"
            )
        rules.append(
            {
                "flag": flag,
                "match": {"operator": operator, "value": value_str},
            }
        )
    return rules


def resolve_auto_user_flag(
    column_config: Optional[Dict[str, Any]],
    *,
    cell_value: Optional[str],
    normalized_value: Optional[str] = None,
) -> Optional[str]:
    """First matching flag rule wins. Returns None when no rule matches."""
    for rule in parse_flag_rules(column_config):
        match = rule["match"]
        condition = RunCondition(
            source_column_id="__self__",
            operator=match["operator"],
            value=match.get("value"),
        )
        if evaluate_run_condition(
            condition,
            source_cell_value=cell_value,
            source_normalized_value=normalized_value,
        ):
            return rule["flag"]
    return None
