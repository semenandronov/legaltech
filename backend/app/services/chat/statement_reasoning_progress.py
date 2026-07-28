"""SSE-friendly progress events for statement reasoning agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

ProgressCallback = Callable[[Dict[str, Any]], None]

_LAWYER_TOOL_LABELS: Dict[str, str] = {
    "statement_context": "Контекст выписки",
    "resolve_entity": "Поиск контрагента в операциях",
    "transactions_query": "Точный запрос к таблице",
    "flow_profile": "Картина денежных потоков",
    "legal_calendar": "Окна 61.2 / 61.3",
    "risk_scan": "Паттерны риска",
    "counterparty_dossier": "Досье контрагента",
    "evidence_bundle": "Пакет строк под процесс",
}


@dataclass
class StatementReasoningProgress:
    """Emits assistant_activity-shaped dicts for operations chat SSE."""

    callback: Optional[ProgressCallback] = None
    total_steps: int = 8
    _seq: int = field(default=0, init=False)

    def _emit(
        self,
        *,
        step_id: str,
        phase: str,
        label: str,
        detail: str = "",
        status: str = "running",
        step: Optional[int] = None,
    ) -> None:
        if not self.callback:
            return
        if step is None:
            self._seq += 1
            step_num = self._seq
        else:
            step_num = step
        detail_text = (detail or "").strip()
        content = f"{label}: {detail_text}" if detail_text else label
        self.callback(
            {
                "step_id": step_id,
                "phase": phase,
                "step": step_num,
                "totalSteps": self.total_steps,
                "label": label,
                "detail": detail_text or None,
                "content": content,
                "status": status,
            }
        )

    def plan_started(self) -> None:
        self._emit(
            step_id="statement_plan",
            phase="statement_plan",
            label="Строю план анализа",
            status="running",
            step=1,
        )

    def plan_ready(self, summary: str) -> None:
        self._emit(
            step_id="statement_plan",
            phase="statement_plan",
            label="План готов",
            detail=(summary or "").strip()[:240],
            status="completed",
            step=1,
        )

    def tool_started(self, tool: str, purpose: str = "") -> None:
        label = _LAWYER_TOOL_LABELS.get(tool, tool)
        self._emit(
            step_id=f"statement_tool_{tool}",
            phase="statement_tool",
            label=label,
            detail=(purpose or "").strip()[:200],
            status="running",
        )

    def tool_done(self, tool: str, purpose: str = "", detail: str = "") -> None:
        label = _LAWYER_TOOL_LABELS.get(tool, tool)
        self._emit(
            step_id=f"statement_tool_{tool}",
            phase="statement_tool",
            label=label,
            detail=(detail or purpose or "готово").strip()[:200],
            status="completed",
        )

    def critique_started(self) -> None:
        self._emit(
            step_id="statement_critique",
            phase="statement_critique",
            label="Проверяю, отвечают ли данные на вопрос",
            status="running",
        )

    def critique_done(self, *, ok: bool, detail: str = "") -> None:
        label = "Проверка пройдена" if ok else "Нужна доработка"
        self._emit(
            step_id="statement_critique",
            phase="statement_critique",
            label=label,
            detail=(detail or "").strip()[:280],
            status="completed" if ok else "running",
        )

    def revise(self, revision: int, hint: str = "") -> None:
        self._emit(
            step_id=f"statement_revise_{revision}",
            phase="statement_revise",
            label=f"Пересборка плана (попытка {revision})",
            detail=(hint or "").strip()[:240],
            status="running",
        )

    def synthesize_started(self) -> None:
        self._emit(
            step_id="statement_synthesize",
            phase="statement_synthesize",
            label="Формирую ответ для юриста",
            status="running",
        )

    def synthesize_done(self) -> None:
        self._emit(
            step_id="statement_synthesize",
            phase="statement_synthesize",
            label="Ответ готов",
            status="completed",
        )
