"""File-scoped ReAct agent: SQL (statement rows) + RAG (document text) for chat and tabular."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional, Sequence

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent
from sqlalchemy.orm import Session

from app.config import config
from app.models.case_file_transaction import CaseFileTransaction
from app.services.case_file_transaction_service import CaseFileTransactionService
from app.services.chat.file_scoped_agent_tools import (
    get_file_scoped_tools,
    pop_file_scoped_rag_documents,
    reset_file_scoped_tool_state,
    scoped_files_have_transactions,
)
from app.services.chat.case_transaction_tools import pop_transaction_tool_citation_rows
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)

FileScopedAgentMode = Literal["chat", "tabular"]

_SQL_TOOL_NAMES = frozenset({"list_case_transactions", "aggregate_case_transactions"})
_SEARCH_TOOL_NAMES = frozenset({"search_in_scoped_files"})
_ALL_TOOL_NAMES = _SQL_TOOL_NAMES | _SEARCH_TOOL_NAMES

_CHAT_SYSTEM_PROMPT = """Ты — ассистент юриста по материалам дела.

Инструменты (область — прикреплённые документы):
- list_case_transactions / aggregate_case_transactions — полный список и суммы операций из банковских выписок (SQL, не top-k);
- search_in_scoped_files — поиск по тексту PDF: шапка, реквизиты, цитаты.

ПРАВИЛА:
1. Вопрос про операции, даты, суммы, платежи → сначала SQL-инструменты.
2. Нужна шапка, банк, счёт, цитата из текста → search_in_scoped_files.
3. Сложный вопрос → можно оба: SQL для цифр, поиск для цитаты.
4. Допускай опечатки («транзкакция», «оперция»).
5. Не выдумывай суммы и даты. Язык: русский."""

_TABULAR_SYSTEM_SUFFIX = """

Режим: заполнение ячейки табличного обзора.
Дай краткий точный ответ на вопрос колонки — одно значение или короткая формулировка, без лишнего текста."""


@dataclass
class FileScopedAgentResult:
    answer: str
    tools_called: bool
    sql_tools_called: bool
    search_tools_called: bool
    context_block: str
    transaction_rows: List[CaseFileTransaction] = field(default_factory=list)
    rag_documents: List[Document] = field(default_factory=list)
    messages: List[Any] = field(default_factory=list)


def agent_enabled() -> bool:
    return bool(getattr(config, "FILE_SCOPED_AGENT_ENABLED", True))


def _tool_names_from_messages(messages: Sequence[Any]) -> set[str]:
    names: set[str] = set()
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in msg.tool_calls or []:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                if name:
                    names.add(str(name))
        if isinstance(msg, ToolMessage):
            name = getattr(msg, "name", None) or (msg.additional_kwargs or {}).get("name")
            if name:
                names.add(str(name))
    return names


def _final_answer(messages: Sequence[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            text = msg.content
            if isinstance(text, list):
                parts: List[str] = []
                for block in text:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(str(block.get("text") or ""))
                    elif isinstance(block, str):
                        parts.append(block)
                text = "".join(parts)
            text = str(text).strip()
            if text:
                return text
    return ""


def _build_context_block(messages: Sequence[Any]) -> str:
    parts: List[str] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            name = getattr(msg, "name", None) or "tool"
            content = str(msg.content or "").strip()
            if content:
                parts.append(f"### {name}\n{content}")
    return "\n\n".join(parts)


def _synthesize_answer_from_sql_tools(messages: Sequence[Any]) -> str:
    """Build user answer from SQL tool output when ReAct did not emit a final message."""
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue
        name = str(getattr(msg, "name", None) or "")
        if name not in _SQL_TOOL_NAMES:
            continue
        content = str(msg.content or "").strip()
        if not content:
            continue
        if "не найден" in content.lower() or "недоступен" in content.lower():
            return content
        if name == "aggregate_case_transactions":
            lines = content.splitlines()
            count_line = next((ln for ln in lines if "Количество операций:" in ln), "")
            sum_line = next((ln for ln in lines if "Сумма" in ln), "")
            period_line = next((ln for ln in lines if ln.startswith("Период:")), "")
            parts = [p for p in (period_line, count_line, sum_line) if p]
            if parts:
                return "\n".join(parts)
        return content
    return ""


def run_file_scoped_agent(
    db: Session,
    *,
    case_id: str,
    question: str,
    file_ids: Sequence[str],
    rag_service,
    mode: FileScopedAgentMode = "chat",
    sql_only: bool = False,
) -> Optional[FileScopedAgentResult]:
    """
    ReAct agent over scoped file(s) with SQL + RAG tools.

    Returns None when disabled, no scope, or agent did not call any tool.
    """
    if not agent_enabled() or not db or not case_id or not (question or "").strip():
        return None

    scope = [str(fid).strip() for fid in file_ids if str(fid).strip()]
    if not scope:
        return None

    # Run agent when scoped files include structured statements OR any file scope for RAG-only docs.
    has_sql = scoped_files_have_transactions(db, case_id, scope)
    tools = get_file_scoped_tools(db, case_id, scope, rag_service, sql_only=sql_only)
    if not tools:
        return None

    reset_file_scoped_tool_state()

    prompt = _CHAT_SYSTEM_PROMPT
    if sql_only:
        prompt = """Ты — ассистент юриста по банковским выпискам.

Инструменты:
- aggregate_case_transactions — для «сколько операций», «итого за период», «общая сумма»;
- list_case_transactions — для списка операций или поиска по дате/времени.

ПРАВИЛА:
1. «Сколько операций» / «количество» → aggregate_case_transactions с date_from и date_to.
2. Конкретная дата/время → list_case_transactions или aggregate с on_date.
3. Не используй текстовый поиск — только SQL-инструменты.
4. Не выдумывай цифры. Язык: русский."""
    if mode == "tabular":
        prompt += _TABULAR_SYSTEM_SUFFIX

    try:
        llm = create_legal_llm(max_tokens=4096 if mode == "chat" else 2048)
        agent = create_react_agent(model=llm, tools=tools, prompt=prompt)
        result = agent.invoke(
            {"messages": [HumanMessage(content=question.strip())]},
            config={"recursion_limit": 10},
        )
        messages = result.get("messages") or []
        tool_names = _tool_names_from_messages(messages)

        if not tool_names & _ALL_TOOL_NAMES:
            logger.info(
                "[FileScopedAgent] case=%s mode=%s no_tools — skip",
                case_id,
                mode,
            )
            reset_file_scoped_tool_state()
            return None

        answer = _final_answer(messages)
        if not answer and bool(tool_names & _SQL_TOOL_NAMES):
            answer = _synthesize_answer_from_sql_tools(messages)
        if not answer:
            reset_file_scoped_tool_state()
            return None

        sql_called = bool(tool_names & _SQL_TOOL_NAMES)
        search_called = bool(tool_names & _SEARCH_TOOL_NAMES)
        tx_rows = pop_transaction_tool_citation_rows() if sql_called else []
        rag_docs = pop_file_scoped_rag_documents() if search_called else []

        logger.info(
            "[FileScopedAgent] case=%s mode=%s sql=%s search=%s tx_rows=%s rag_docs=%s",
            case_id,
            mode,
            sql_called,
            search_called,
            len(tx_rows),
            len(rag_docs),
        )

        return FileScopedAgentResult(
            answer=answer,
            tools_called=True,
            sql_tools_called=sql_called,
            search_tools_called=search_called,
            context_block=_build_context_block(messages),
            transaction_rows=tx_rows,
            rag_documents=rag_docs,
            messages=list(messages),
        )

    except Exception as exc:
        logger.error("[FileScopedAgent] failed case=%s: %s", case_id, exc, exc_info=True)
        reset_file_scoped_tool_state()
        return None
