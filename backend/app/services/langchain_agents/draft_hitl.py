"""
Общая логика HITL для режима Draft: явное одобрение/отклонение плана.

Используется оркестратором и узлами графа, чтобы не было ложных срабатываний
(например «не одобряю» → ошибочно трактуется как одобрение).
"""
from __future__ import annotations

import re
from typing import Optional

# Короткая реплика — одобрение (как в UI-кнопке / явной команде).
_APPROVAL_PATTERNS = (
    r"^одобряю\b",
    r"^подтверждаю\b",
    r"^согласен\b",
    r"^согласна\b",
    r"^да,?\s+генерируй\b",
    r"^да,?\s+создавай\b",
    r"^генерируй\b",
    r"^создавай\b",
    r"^можно\s+генерировать\b",
    r"^подтверждаю\s+создание\b",
    r"^всё\s+верно,?\s+генерируй\b",
    r"^все\s+верно,?\s+генерируй\b",
    r"^одобрить\s+план\b",
    r"^одобрить\s+и\s+создать\b",
)

_DRAFT_REJECT_RE = re.compile(
    r"\b(?:отмен\w*|не\s+одобр\w*|не\s+соглас\w*|стоп)\b",
    re.IGNORECASE,
)


def is_explicit_draft_approval_message(text: str) -> bool:
    """
    Явное подтверждение генерации черновика (короткая фраза).
    Не считать одобрением длинные сообщения и фразы с отрицанием.
    """
    q = (text or "").strip()
    if not q or len(q) > 160:
        return False
    ql = q.lower()
    if re.search(r"\bне\s+одобр", ql):
        return False
    if re.search(r"\bне\s+соглас", ql):
        return False
    if re.search(r"\bне\s+подтвержд", ql):
        return False
    return any(re.search(p, ql) for p in _APPROVAL_PATTERNS)


def is_explicit_draft_reject_message(text: str) -> bool:
    """Явный отказ / отмена (для текстовой команды в чате)."""
    return bool(_DRAFT_REJECT_RE.search(text or ""))


def normalize_draft_action(raw: Optional[str]) -> Optional[str]:
    """Привести значение из API к 'approve' | 'reject' | None."""
    if raw is None or raw == "":
        return None
    s = str(raw).strip().lower()
    if s in ("approve", "accept", "confirm"):
        return "approve"
    if s in ("reject", "cancel", "decline"):
        return "reject"
    return None
