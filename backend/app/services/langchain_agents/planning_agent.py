"""
PlanningAgent — детерминированный планировщик для /api/chat/task.

Цель: быстро определить тип(ы) анализа по формулировке задачи пользователя.
Без сетевых вызовов и без LLM-циклов — это входной router, а не "умный" агент.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def create_legal_agent(*args, **kwargs) -> Any:
    """
    Legacy hook for tests/backwards-compat.
    Ранее здесь мог инициализироваться LLM/agent; сейчас планирование детерминированное.
    """

    return None


_CMD_RE = re.compile(
    r"\b(?:"
    r"проанализируй|анализируй|выполни|найди|извлеки|создай|сделай|запусти|проведи|провести|"
    r"analyze|extract|find|create|generate|run|perform|execute"
    r")\b",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(r"^\s*(как|что|почему|зачем|когда|где|кто|какие?)\b", re.IGNORECASE)

_TIMELINE_RE = re.compile(r"\b(timeline|таймлайн|хронолог|срок|дата)\b", re.IGNORECASE)
_DISCREPANCY_RE = re.compile(r"\b(discrepanc|противореч|несоответств)\b", re.IGNORECASE)
_RISK_RE = re.compile(r"\b(risk|рис(к|ки)|риск(и|ов)?|опасност)\b", re.IGNORECASE)
_KEY_FACTS_RE = re.compile(r"\b(key\s*facts|ключев\w*\s+факт\w*|факт\w*)\b", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"\b(summary|резюм\w*|кратк\w+\s+сводк\w*|обзор)\b", re.IGNORECASE)


class PlanningAgent:
    """
    Планировщик анализов по NL-задаче.

    Возвращает plan dict с ключом analysis_types:
    - timeline
    - key_facts
    - discrepancy
    - risk
    - summary
    """

    def __init__(self) -> None:
        self._agent = create_legal_agent()

    def plan_analysis(self, *, user_task: str, case_id: Optional[str] = None) -> Dict[str, Any]:
        text = (user_task or "").strip()
        if not text:
            return {"analysis_types": [], "confidence": 0.0, "reasoning": "Пустая задача"}

        analysis: List[str] = []
        if _TIMELINE_RE.search(text):
            analysis.append("timeline")
        if _DISCREPANCY_RE.search(text):
            analysis.append("discrepancy")
        if _RISK_RE.search(text):
            analysis.append("risk")
        if _KEY_FACTS_RE.search(text):
            analysis.append("key_facts")
        if _SUMMARY_RE.search(text):
            analysis.append("summary")

        # Если это команда, но по ключевым словам ничего не нашли — делаем safe default.
        if not analysis and _CMD_RE.search(text) and not _QUESTION_RE.search(text) and "?" not in text:
            analysis = ["summary"]

        confidence = 0.8 if analysis else 0.4
        reasoning = "План сформирован по ключевым словам задачи"
        return {
            "analysis_types": analysis,
            "confidence": confidence,
            "reasoning": reasoning,
            "case_id": case_id,
        }

