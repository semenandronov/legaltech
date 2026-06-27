"""
Ask → Edit handoff: structured issue targets survive across turns.

When Ask identifies document problems, we persist ``pending_edit_targets`` in graph
state so Edit execution must cover every listed location (fail-closed otherwise).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.langchain_agents.graphs.editor_edit_pipeline import (
    instruction_is_dialogue_continuation,
)
from app.services.langchain_agents.graphs.editor_transcript import (
    editor_transcript_for_prompt,
    message_role,
    message_text,
)

_ISSUE_SIGNALS = (
    "несоответств",
    "расхожден",
    "отлича",
    "ошибк",
    "неверно",
    "не совпада",
    "проблем",
    "нужно исправ",
    "нужно замен",
    "следует исправ",
    "следует замен",
    "некоррект",
)

_LOCATION_HINTS = (
    "пункт",
    "раздел",
    "просительн",
    "абзац",
    "таблиц",
    "блок",
    "част",
    "расчёт",
    "расчет",
    "основан",
    "заключен",
    "шапк",
    "прилож",
    "вводн",
    "преамбул",
)

_LIST_ITEM_RE = re.compile(
    r"^\s*(?:"
    r"(\d+)[.)]\s+"
    r"|[-•*]\s+"
    r")(.+)$",
    re.MULTILINE,
)

_EXPLICIT_COUNT_RE = re.compile(
    r"(?:"
    r"(\d+)\s+несоответств"
    r"|в\s+(\d+)\s+мест"
    r"|(\d+)\s+мест[ае]?"
    r"|найден[оа]\s+(\d+)"
    r")",
    re.IGNORECASE,
)

_WORD_COUNT_MAP = {
    "два": 2,
    "две": 2,
    "двух": 2,
    "двум": 2,
    "три": 3,
    "трёх": 3,
    "трех": 3,
    "трем": 3,
    "трём": 3,
    "четыре": 4,
    "четырёх": 4,
    "четырех": 4,
}


def _line_looks_like_issue(line: str) -> bool:
    low = (line or "").strip().lower()
    if len(low) < 8:
        return False
    if any(hint in low for hint in _LOCATION_HINTS):
        return True
    if any(signal in low for signal in _ISSUE_SIGNALS):
        return True
    if re.search(r"\d[\d\s]*(?:руб|₽|млн|тыс)", low):
        return True
    return False


def count_explicit_issue_count(text: str) -> int:
    """Parse phrases like «2 несоответствия», «в двух местах»."""
    src = (text or "").strip().lower()
    if not src:
        return 0

    for match in _EXPLICIT_COUNT_RE.finditer(src):
        for group in match.groups():
            if group and group.isdigit():
                return max(1, int(group))

    for word, count in _WORD_COUNT_MAP.items():
        if re.search(rf"\b{re.escape(word)}\s+мест", src):
            return count
        if re.search(rf"\b{re.escape(word)}\s+несоответств", src):
            return count

    return 0


def parse_assistant_identified_issues(text: str) -> List[Dict[str, str]]:
    """
    Extract issue rows from an Ask assistant reply (numbered / bullet lists).

    Returns targets: {location, change} suitable for pending_edit_targets.
    """
    src = (text or "").strip()
    if not src:
        return []

    issues: List[Dict[str, str]] = []
    seen: set[str] = set()

    for match in _LIST_ITEM_RE.finditer(src):
        body = (match.group(2) or "").strip()
        if not _line_looks_like_issue(body):
            continue
        key = body.lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        location = body[:160]
        issues.append(
            {
                "location": location,
                "change": body[:400],
                "node_id": None,
            }
        )

    return issues


def last_assistant_message_text(state: Dict[str, Any]) -> str:
    """Most recent assistant message before the current user question."""
    msgs = list(state.get("messages") or [])
    if len(msgs) <= 1:
        return ""
    for msg in reversed(msgs[:-1]):
        if message_role(msg) == "assistant":
            return message_text(msg)
    return ""


def build_pending_targets_from_assistant_text(text: str) -> List[Dict[str, Any]]:
    """Build pending_edit_targets from a fresh Ask response."""
    issues = parse_assistant_identified_issues(text)
    if issues:
        return issues

    explicit = count_explicit_issue_count(text)
    if explicit >= 2:
        return [
            {
                "location": f"несоответствие {idx + 1} из анализа ассистента",
                "change": "исправить согласно предыдущему ответу ассистента",
                "node_id": None,
            }
            for idx in range(explicit)
        ]
    return []


def resolve_minimum_target_count(
    state: Dict[str, Any],
    question: str,
) -> Optional[int]:
    """
    Minimum number of edit targets required for this Edit turn.

    Returns None when there is no floor (direct edit request without prior analysis).
    """
    pending = state.get("pending_edit_targets") or []
    if isinstance(pending, list) and pending:
        return max(1, len(pending))

    if not instruction_is_dialogue_continuation(question):
        return None

    last = last_assistant_message_text(state)
    if not last:
        return None

    issues = parse_assistant_identified_issues(last)
    if issues:
        return len(issues)

    explicit = count_explicit_issue_count(last)
    if explicit >= 2:
        return explicit

    return None


def format_pending_targets_block(targets: List[Dict[str, Any]]) -> str:
    if not targets:
        return ""
    lines = [
        "ОБЯЗАТЕЛЬНЫЕ ЦЕЛИ ИЗ ПРЕДЫДУЩЕГО АНАЛИЗА (нельзя уменьшать число целей):",
    ]
    for idx, target in enumerate(targets, start=1):
        if not isinstance(target, dict):
            continue
        loc = (target.get("location") or "").strip()
        change = (target.get("change") or "").strip()
        node_id = target.get("node_id")
        row = f"{idx}. {loc}"
        if change and change != loc:
            row += f" — {change}"
        if node_id:
            row += f" [node_id={node_id}]"
        lines.append(row)
    return "\n".join(lines)


def format_minimum_targets_hint(minimum: int) -> str:
    return (
        f"МИНИМУМ ЦЕЛЕЙ: {minimum}. "
        f"scope.target_count и len(scope.targets) должны быть >= {minimum}. "
        "Каждая цель из предыдущего анализа — отдельная запись в targets."
    )


def scope_meets_minimum(
    scope: Optional[Dict[str, Any]],
    minimum: Optional[int],
) -> bool:
    if minimum is None or minimum <= 1:
        return True
    if not scope or not isinstance(scope, dict):
        return False
    targets = scope.get("targets") or []
    if not isinstance(targets, list):
        return False
    target_count = scope.get("target_count")
    if isinstance(target_count, int) and target_count >= minimum:
        return len(targets) >= minimum
    return len(targets) >= minimum


def merge_pending_into_scope(
    scope: Dict[str, Any],
    pending: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    When the model under-planned but we have pending targets from Ask,
    adopt pending targets as the authoritative scope.
    """
    if not pending:
        return scope

    targets = []
    for row in pending:
        if not isinstance(row, dict):
            continue
        targets.append(
            {
                "location": (row.get("location") or "").strip() or "документ",
                "change": (row.get("change") or "").strip() or "исправить",
                "node_id": row.get("node_id"),
            }
        )
    if not targets:
        return scope

    return {
        "target_count": len(targets),
        "targets": targets,
    }
