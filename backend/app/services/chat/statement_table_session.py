"""Per-turn session state for the statement table tool-calling agent."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_sql_executor import StatementSqlExecutionResult
from app.services.chat.statement_sql_facts import StatementSqlFacts
from app.services.chat.statement_sql_models import StatementSqlPlan

_session_var: ContextVar[Optional["StatementTableSession"]] = ContextVar(
    "statement_table_session",
    default=None,
)


@dataclass
class StatementTableSession:
    """Scoped runtime for one agent turn — never shared across requests."""

    case_id: str
    file_id: str
    file_label: str
    question: str = ""
    db: Optional[Session] = None
    # When set, queries run in-memory over this row set (UI-filtered operations chat).
    rows: Optional[Sequence[CaseFileTransaction]] = None
    scope_note: str = ""
    citation_rows: List[CaseFileTransaction] = field(default_factory=list)
    last_plan: Optional[StatementSqlPlan] = None
    last_facts: Optional[StatementSqlFacts] = None
    last_execution: Optional[StatementSqlExecutionResult] = None
    tool_calls: List[str] = field(default_factory=list)

    @property
    def uses_in_memory_rows(self) -> bool:
        return self.rows is not None


def get_statement_table_session() -> StatementTableSession:
    session = _session_var.get()
    if session is None:
        raise RuntimeError("Statement table agent session is not initialized")
    return session


def bind_statement_table_session(session: StatementTableSession):
    """Context manager that binds session for tool execution."""
    return _StatementTableSessionBind(session)


class _StatementTableSessionBind:
    def __init__(self, session: StatementTableSession) -> None:
        self._session = session
        self._token = None

    def __enter__(self) -> StatementTableSession:
        self._token = _session_var.set(self._session)
        return self._session

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            _session_var.reset(self._token)
