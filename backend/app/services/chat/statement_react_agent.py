"""
Statement ReAct agent — единый цикл Reason → Action (Python sandbox) → Observation
для всех вопросов на странице «Операции».
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from typing import Any, Dict, List, Mapping, Optional, Sequence

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent
from sqlalchemy.orm import Session

from app.config import config
from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.conversation_turn_state import ConversationTurnState
from app.services.chat.statement_react_session import (
    ProgressCallback,
    StatementReActSession,
    bind_statement_react_session,
    reset_statement_react_session,
)
from app.services.chat.statement_react_tools import build_statement_react_tools
from app.services.chat.statement_scope_export import export_statement_scope_dataset
from app.services.chat.statement_react_progress import emit_statement_react_progress
from app.services.chat.statement_sql_planner import format_statement_sql_conversation_history
from app.services.llm_factory import create_legal_llm, user_facing_llm_reasoning_kwargs

logger = logging.getLogger(__name__)

ConversationHistory = Sequence[Mapping[str, Any]]

_REACT_TOOL_NAMES = frozenset({"run_python_code", "describe_statement_dataset"})
_UUID_IN_TEXT = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)

_SYSTEM_PROMPT = """Ты — старший финансовый аналитик в команде юристов (банкротство, оспаривание сделок).

Твой цикл работы — ReAct:
1) Сформулируй гипотезу (мысленно).
2) Вызови describe_statement_dataset при необходимости.
3) Напиши Python (run_python_code): pandas, df уже загружен. Все расчёты — в коде.
4) Прочитай observation (stdout/stderr), при ошибке исправь код и повтори.
5) Ответ юристу — только на основе успешных observations.

Правила:
- Числа, даты, количества — ТОЛЬКО из stdout инструментов, не «из головы».
- Любой тип вопроса (контрагент, список, сумма, «сколько», дробление, аномалии) — только через Python.
- Поиск ФИО/контрагента: несколько проходов в коде (фамилия, имя+отчество, подстроки в description), не считай всю выписку без фильтра.
- Простые запросы («операции > 10к») — фильтр df и print(count/sum/head).
- Контрагента часто нужно извлекать из description (подстроки, regex).
- amount_rub: минус — списание, плюс — поступление.
- Не выноси судебных вердиктов; формулируй «признаки / стоит проверить» в тексте фактов, если уместно.
- Структура ответа: краткий вывод → факты с цифрами. Отдельного блока «что проверить дальше» не добавляй.
- Язык: русский. Даты: как в данных или DD.MM.YYYY.

Запрещено отвечать по существу без хотя бы одного успешного run_python_code."""


def react_agent_enabled() -> bool:
    return bool(getattr(config, "STATEMENT_REACT_AGENT_ENABLED", True))


def _max_steps() -> int:
    return max(4, int(getattr(config, "STATEMENT_REACT_MAX_STEPS", 14) or 14))


def _max_tokens() -> int:
    return max(1024, int(getattr(config, "STATEMENT_REACT_MAX_TOKENS", 4096) or 4096))


def _tool_names_from_messages(messages: Sequence[Any]) -> set[str]:
    names: set[str] = set()
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in msg.tool_calls or []:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                if name:
                    names.add(str(name))
        if isinstance(msg, ToolMessage):
            name = getattr(msg, "name", None)
            if name:
                names.add(str(name))
    return names


def _final_ai_text(messages: Sequence[Any]) -> str:
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage) or msg.tool_calls:
            continue
        content = msg.content
        if isinstance(content, list):
            parts: List[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif isinstance(block, str):
                    parts.append(block)
            content = "".join(parts)
        text = str(content or "").strip()
        if text:
            return text
    return ""


def _observation_blob(messages: Sequence[Any]) -> str:
    chunks: List[str] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            chunks.append(str(msg.content or ""))
    return "\n".join(chunks)


def _successful_python_runs(messages: Sequence[Any]) -> bool:
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        try:
            data = json.loads(str(msg.content or ""))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("ok") and "stdout" in data:
            return True
    return False


def _build_user_message(
    *,
    question: str,
    file_label: str,
    scope_note: str,
    row_count: int,
    conversation_history: Optional[ConversationHistory],
) -> str:
    parts: List[str] = []
    if scope_note.strip():
        parts.append(scope_note.strip())
    parts.append(f"Файл: {file_label}. Строк в scope: {row_count}.")
    history = format_statement_sql_conversation_history(conversation_history or [])
    if history:
        parts.append("Контекст диалога (не источник чисел):")
        parts.append(history)
    parts.append("Вопрос юриста:")
    parts.append(question.strip())
    return "\n\n".join(parts)


def _citations_from_observations(
    db: Session,
    case_id: str,
    rows: Sequence[CaseFileTransaction],
    blob: str,
) -> List[Dict[str, Any]]:
    ids = {m.group(0) for m in _UUID_IN_TEXT.finditer(blob)}
    if not ids:
        return []
    by_id = {str(r.id): r for r in rows}
    matched = [by_id[i] for i in ids if i in by_id]
    if not matched:
        return []
    from app.services.chat.case_transaction_graph import build_transaction_citations

    return build_transaction_citations(db, case_id, matched[:20])


def run_statement_react_agent(
    db: Session,
    *,
    case_id: str,
    question: str,
    file_id: str,
    file_label: str,
    rows: Sequence[CaseFileTransaction],
    scope_note: str = "",
    conversation_history: Optional[ConversationHistory] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Optional[Dict[str, Any]]:
    if not react_agent_enabled():
        return None
    q = (question or "").strip()
    fid = (file_id or "").strip()
    if not db or not case_id or not q or not fid or not rows:
        return None

    label = (file_label or "").strip() or "выписка"
    dataset = export_statement_scope_dataset(
        rows,
        file_label=label,
        scope_note=scope_note,
    )
    session = StatementReActSession(
        case_id=case_id,
        file_id=fid,
        file_label=label,
        question=q,
        scope_note=scope_note or "",
        work_dir=dataset.work_dir,
        csv_path=dataset.csv_path,
        manifest_path=dataset.manifest_path,
        row_count=dataset.row_count,
        progress=progress_callback,
    )

    token = bind_statement_react_session(session)
    try:
        if progress_callback:
            emit_statement_react_progress(
                progress_callback,
                step_id="react_think",
                phase="react_think",
                label="Формирую план анализа",
                status="running",
                step=1,
            )

        llm = create_legal_llm(
            temperature=0.0,
            max_tokens=_max_tokens(),
            use_rate_limiting=False,
            **user_facing_llm_reasoning_kwargs(mode="normal"),
        )
        agent = create_react_agent(
            model=llm,
            tools=build_statement_react_tools(),
            prompt=_SYSTEM_PROMPT,
        )
        user_text = _build_user_message(
            question=q,
            file_label=label,
            scope_note=scope_note,
            row_count=len(rows),
            conversation_history=conversation_history,
        )
        result = agent.invoke(
            {"messages": [HumanMessage(content=user_text)]},
            config={"recursion_limit": _max_steps()},
        )
        messages = result.get("messages") or []
        tool_names = _tool_names_from_messages(messages)

        if not tool_names & _REACT_TOOL_NAMES:
            logger.info("[StatementReAct] no tools case=%s", case_id)
            return None
        if not _successful_python_runs(messages):
            logger.info("[StatementReAct] no successful python run case=%s", case_id)
            return None

        answer = _final_ai_text(messages)
        if not answer:
            logger.info("[StatementReAct] empty final message case=%s", case_id)
            return None

        blob = _observation_blob(messages)
        citations = _citations_from_observations(db, case_id, rows, blob)

        turn_state = ConversationTurnState(
            domain="statement_analytics",
            statement_file_id=fid,
            structured_data_plane="react_python",
            topic_file_ids=(fid,),
        ).to_dict()

        if progress_callback:
            emit_statement_react_progress(
                progress_callback,
                step_id="react_think",
                phase="react_think",
                label="Формирую план анализа",
                status="completed",
                step=1,
            )

        return {
            "transaction_agent_resolved": True,
            "response": answer,
            "messages": [AIMessage(content=answer)],
            "citations": citations,
            "outbound_turn_state": turn_state,
            "statement_sql_meta": {
                "resolver": "statement_react_agent",
                "operation": "react_python",
                "row_count": len(rows),
                "file_id": fid,
                "tool_calls": sorted(tool_names),
                "code_runs": len(session.code_runs),
            },
        }
    except Exception as exc:
        logger.warning("[StatementReAct] failed case=%s: %s", case_id, exc)
        return None
    finally:
        reset_statement_react_session(token)
        try:
            shutil.rmtree(session.work_dir, ignore_errors=True)
        except OSError:
            pass
