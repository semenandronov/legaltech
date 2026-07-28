"""Context for one statement ReAct turn (dataset path + audit trail)."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ProgressCallback = Callable[[Dict[str, Any]], None]


@dataclass
class StatementReActSession:
    case_id: str
    file_id: str
    file_label: str
    question: str
    scope_note: str
    work_dir: Path
    csv_path: Path
    manifest_path: Path
    row_count: int
    progress: Optional[ProgressCallback] = None
    code_runs: List[Dict[str, Any]] = field(default_factory=list)

    def record_run(self, *, code: str, observation: str, ok: bool) -> None:
        self.code_runs.append(
            {
                "ok": ok,
                "code_preview": (code or "")[:400],
                "observation_preview": (observation or "")[:800],
            }
        )


_session_var: ContextVar[Optional[StatementReActSession]] = ContextVar(
    "statement_react_session",
    default=None,
)


def bind_statement_react_session(session: StatementReActSession):
    return _session_var.set(session)


def reset_statement_react_session(token) -> None:
    _session_var.reset(token)


def get_statement_react_session() -> Optional[StatementReActSession]:
    return _session_var.get()
