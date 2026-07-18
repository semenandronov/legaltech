"""Per-turn session state for the statement table tool-calling agent."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from app.config import config
from app.models.case_file_transaction import CaseFileTransaction
from app.services.case_file_transaction_service import CaseFileTransactionService
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
    # Deterministic summaries produced by analytical (insight) tools — used as a
    # grounded fallback answer when the model returns no final text.
    analysis_findings: List[str] = field(default_factory=list)
    # Whole-statement analytics scope. Set by load_all_rows(): total_row_count is the
    # true number of rows in the statement; rows_truncated flags that analytics ran on
    # a capped subset, so tools MUST warn the lawyer instead of reporting silently.
    total_row_count: Optional[int] = None
    analyzed_row_count: Optional[int] = None
    rows_truncated: bool = False

    @property
    def uses_in_memory_rows(self) -> bool:
        return self.rows is not None

    def load_all_rows(self) -> List[CaseFileTransaction]:
        """Full row set for whole-statement analytics (in-memory scope or DB load).

        Records total_row_count / rows_truncated so analytical tools can disclose when
        the statement exceeds the analysis cap (numbers would otherwise be understated).
        """
        if self.rows is not None:
            loaded = list(self.rows)
            self.total_row_count = len(loaded)
            self.analyzed_row_count = len(loaded)
            self.rows_truncated = False
            return loaded
        if self.db is None:
            self.total_row_count = 0
            self.analyzed_row_count = 0
            self.rows_truncated = False
            return []
        max_rows = max(
            5000,
            int(getattr(config, "OPERATIONS_CHAT_SCOPE_MAX_ROWS", 20000) or 20000),
        )
        page = CaseFileTransactionService.query_page(
            self.db,
            case_id=self.case_id,
            file_id=self.file_id,
            order_by="date_asc",
            limit=max_rows,
            offset=0,
        )
        loaded = list(page.rows)
        self.total_row_count = int(page.total)
        self.analyzed_row_count = len(loaded)
        self.rows_truncated = page.total > len(loaded)
        return loaded

    def add_citation_rows(self, rows: Sequence[CaseFileTransaction]) -> None:
        """Register rows surfaced by a tool so the answer can link them in the PDF."""
        seen = {r.id for r in self.citation_rows}
        for row in rows:
            if row.id not in seen:
                self.citation_rows.append(row)
                seen.add(row.id)


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
