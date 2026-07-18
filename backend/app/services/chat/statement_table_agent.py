"""
Statement table agent — LangChain create_agent over domain tools.

The model reasons and chooses tools (inspect / probe / query). All numbers come from
the deterministic statement SQL executor. Final user text is fact-bound synthesis,
not free-form agent prose for aggregates.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.orm import Session

from app.config import config
from app.models.case_file_transaction import CaseFileTransaction
from app.services.case_file_transaction_service import CaseFileTransactionService
from app.services.chat.conversation_turn_state import (
    ConversationTurnState,
    turn_state_from_sql_plan,
)
from app.services.chat.statement_sql_facts import compose_fallback_answer
from app.services.chat.statement_sql_planner import (
    file_display_name,
    format_statement_sql_conversation_history,
)
from app.services.chat.statement_sql_synthesizer import synthesize_statement_sql_answer
from app.services.chat.statement_insight_tools import (
    INSIGHT_TOOL_NAMES,
    build_statement_insight_tools,
)
from app.services.chat.statement_table_session import (
    StatementTableSession,
    bind_statement_table_session,
)
from app.services.chat.statement_table_tools import build_statement_table_tools
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)

ConversationHistory = Sequence[Mapping[str, Any]]

_SYSTEM_PROMPT = """Ты — финансовый аналитик, помогающий юристу разобрать одну банковскую выписку \
(контекст — банкротство и оспаривание сделок). Твоя задача — не просто отвечать на \
буквальный вопрос, а помогать: находить зацепки, объяснять, что они значат, и \
предлагать следующий шаг проверки.

Инструменты (числа берутся ТОЛЬКО из их ответов):
Точечные запросы:
1) inspect_statement — краткий обзор (счётчик, даты, примеры описаний).
2) probe_description — проверка токена контрагента/назначения перед фильтром.
3) query_statement — count/sum/list/find/top/group по фильтрам.
Аналитические:
4) statement_overview — полный профиль: приток/отток/сальдо, крупнейшие контрагенты и
   операции, объём наличных. Вызови первым на открытые вопросы («что в выписке»,
   «на что обратить внимание»). Поддерживает date_from/date_to.
5) monthly_breakdown — приток/отток/сальдо по месяцам (тренды, «куда уходят деньги»).
6) detect_anomalies — подозрительные паттерны (дробление, транзит «пришло-ушло»,
   снятия наличных, крупные и круглые переводы, систематические переводы, всплески
   оттока). Вызови на «что подозрительного», «вывод активов». Поддерживает date_from/date_to.
7) counterparty_profile — карточка одного контрагента (суммы, период, примеры).
8) suspicion_period_analysis — разбор по периодам подозрительности банкротства
   (1 мес / 6 мес / 1 год / 3 года) от даты принятия заявления (ст. 61.2/61.3).
   Вызови, если указана дата принятия заявления или вопрос про «подозрительный период».
9) category_breakdown — структура операций по категориям (наличные, займы, налоги,
   ЖКХ, зарплата, переводы физлицам, покупки). Для «на что уходят деньги», «покажи
   займы и переводы физлицам».

Как работать:
- Открытый/оценочный вопрос → начни со statement_overview, при необходимости добавь
  detect_anomalies / monthly_breakdown / category_breakdown, затем дай связный вывод.
- Есть дата принятия заявления или речь о «подозрительном периоде» → suspicion_period_analysis;
  чтобы углубиться в конкретное окно — передавай date_from/date_to в другие инструменты.
- Конкретный вопрос («сколько», «в 19:28», «топ-5») → query_statement.
- Перед description_contains/counterparty_profile с коротким токеном — probe_description.
- Не выдумывай суммы, даты, количества и выводы. Всё — из ответов инструментов.
- Не делай юридических заключений («притворная сделка», «преднамеренное банкротство»).
  Формулируй как зону внимания: «стоит проверить», «требует объяснения».
- Даты только DD.MM.YYYY. amount_semantics=debit для списаний, credit для поступлений.
- Ответ структурируй: короткий вывод → факты с цифрами → что проверить дальше.
- Язык ответа: русский, деловой и конкретный."""


def statement_table_agent_enabled() -> bool:
    return bool(getattr(config, "STATEMENT_TABLE_AGENT_ENABLED", True))


def _max_tool_calls() -> int:
    return max(2, int(getattr(config, "STATEMENT_TABLE_AGENT_MAX_TOOL_CALLS", 8) or 8))


def _max_tokens() -> int:
    return max(512, int(getattr(config, "STATEMENT_TABLE_AGENT_MAX_TOKENS", 2048) or 2048))


def _build_middleware() -> list:
    layers: list = []
    try:
        from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware

        layers.append(
            ToolCallLimitMiddleware(
                run_limit=_max_tool_calls(),
                exit_behavior="continue",
            )
        )
    except Exception as exc:
        logger.warning("[StatementTableAgent] ToolCallLimitMiddleware unavailable: %s", exc)
    return layers


def _final_ai_text(messages: Sequence[Any]) -> str:
    for msg in reversed(list(messages)):
        if not isinstance(msg, AIMessage):
            continue
        if getattr(msg, "tool_calls", None):
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


def _build_user_payload(
    *,
    question: str,
    file_id: str,
    file_label: str,
    scope_note: str,
    sql_plan_hints: Optional[dict],
    conversation_history: Optional[ConversationHistory],
) -> str:
    history = format_statement_sql_conversation_history(conversation_history)
    hints = sql_plan_hints or {}
    hint_lines = []
    for key in (
        "date_from",
        "date_to",
        "on_date",
        "description_contains",
        "amount_semantics",
        "operation",
    ):
        val = str(hints.get(key) or "").strip()
        if val:
            hint_lines.append(f"- {key}: {val}")
    parts = [
        f"Выписка: «{file_label}» (file_id={file_id}).",
    ]
    if scope_note.strip():
        parts.append(f"Область: {scope_note.strip()}")
    if hint_lines:
        parts.append("Подсказки предыдущего хода (необязательны, проверь сам):")
        parts.extend(hint_lines)
    if history:
        parts.append("Предыдущий диалог (контекст, НЕ источник чисел):")
        parts.append(history)
    parts.append("Текущий вопрос юриста:")
    parts.append(question.strip())
    parts.append(
        "Выбери инструмент под задачу: конкретный вопрос («сколько», «топ-5», "
        "«в дату/время») → query_statement (при необходимости сначала inspect/probe); "
        "открытый/оценочный («что в выписке», «что подозрительного», «тренды», "
        "профиль контрагента) → statement_overview / detect_anomalies / "
        "monthly_breakdown / category_breakdown / counterparty_profile; про периоды "
        "подозрительности или при известной дате принятия заявления → "
        "suspicion_period_analysis (при углублении передавай date_from/date_to). "
        "Все числа и выводы бери ТОЛЬКО из ответов инструментов."
    )
    return "\n".join(parts)


def _compose_insight_fallback(session: StatementTableSession) -> str:
    """Deterministic answer from tool summaries when the model returns no prose."""
    seen: set[str] = set()
    unique: List[str] = []
    for line in session.analysis_findings:
        text = (line or "").strip()
        if text and text not in seen:
            seen.add(text)
            unique.append(text)
    return "\n\n".join(unique).strip()


def _insight_patch(
    *,
    db: Session,
    case_id: str,
    session: StatementTableSession,
    final_text: str,
) -> Optional[Dict[str, Any]]:
    """Advisory answer built from analytical tools (numbers already in tool output)."""
    answer = (final_text or "").strip() or _compose_insight_fallback(session)
    if not answer:
        return None

    citations: List[Dict[str, Any]] = []
    if session.citation_rows:
        # Deferred import: case_transaction_graph -> case_transaction_agent ->
        # statement_sql_pipeline -> statement_table_agent forms an import cycle.
        from app.services.chat.case_transaction_graph import build_transaction_citations

        citations = build_transaction_citations(
            db, case_id=case_id, rows=session.citation_rows[:20]
        )

    if session.last_plan is not None:
        outbound = turn_state_from_sql_plan(
            plan=session.last_plan,
            file_id=session.file_id,
            plane="sql",
        ).to_dict()
    else:
        outbound = ConversationTurnState(
            domain="statement_analytics",
            statement_file_id=session.file_id,
            structured_data_plane="sql",
            topic_file_ids=(session.file_id,),
        ).to_dict()

    return {
        "transaction_agent_resolved": True,
        "response": answer,
        "messages": [AIMessage(content=answer)],
        "citations": citations,
        "outbound_turn_state": outbound,
        "statement_sql_meta": {
            "resolver": "table_agent_insight",
            "operation": "insight",
            "row_count": len(session.citation_rows),
            "file_id": session.file_id,
            "tool_calls": list(session.tool_calls),
        },
    }


def _patch_from_session(
    *,
    db: Session,
    case_id: str,
    session: StatementTableSession,
    question: str,
    conversation_history: Optional[ConversationHistory],
) -> Optional[Dict[str, Any]]:
    if session.last_execution is None or session.last_facts is None or session.last_plan is None:
        return None

    plan = session.last_plan
    execution = session.last_execution
    synthesis = synthesize_statement_sql_answer(
        question=question,
        plan=plan,
        execution=execution,
        conversation_history=conversation_history,
    )
    answer = (synthesis.text or "").strip()
    if not answer:
        answer = compose_fallback_answer(
            question=question,
            plan=plan,
            facts=session.last_facts,
        ).strip()
    if not answer:
        return None

    if execution.facts.row_count == 0 and plan.operation in {"list", "find"}:
        return {
            "sql_attempted_empty": True,
            "statement_sql_meta": {
                "resolver": "table_agent",
                "operation": plan.operation,
                "row_count": 0,
                "file_id": session.file_id,
                "date_from": plan.date_from,
                "date_to": plan.date_to,
                "on_date": plan.on_date,
                "tool_calls": list(session.tool_calls),
            },
        }

    citations: List[Dict[str, Any]] = []
    cite_rows = session.citation_rows or list(execution.rows)
    if cite_rows:
        # Deferred import: case_transaction_graph -> case_transaction_agent ->
        # statement_sql_pipeline -> statement_table_agent forms an import cycle.
        from app.services.chat.case_transaction_graph import build_transaction_citations

        citations = build_transaction_citations(db, case_id=case_id, rows=cite_rows[:20])

    outbound = turn_state_from_sql_plan(
        plan=plan,
        file_id=session.file_id,
        plane="sql",
    ).to_dict()

    return {
        "transaction_agent_resolved": True,
        "response": answer,
        "messages": [AIMessage(content=answer)],
        "citations": citations,
        "outbound_turn_state": outbound,
        "statement_sql_meta": {
            "resolver": "table_agent",
            "operation": plan.operation,
            "row_count": execution.facts.row_count,
            "synthesized": synthesis.via_llm,
            "file_id": session.file_id,
            "date_from": plan.date_from,
            "date_to": plan.date_to,
            "on_date": plan.on_date,
            "description_contains": plan.description_contains,
            "tool_calls": list(session.tool_calls),
        },
    }


def run_statement_table_agent(
    db: Session,
    *,
    case_id: str,
    question: str,
    file_id: str,
    file_label: str = "",
    rows: Optional[Sequence[CaseFileTransaction]] = None,
    scope_note: str = "",
    sql_plan_hints: Optional[dict] = None,
    conversation_history: Optional[ConversationHistory] = None,
) -> Optional[Dict[str, Any]]:
    """
    Tool-calling agent over one statement file.

    Returns the same patch shape as ``run_statement_sql_pipeline``, or None on failure.
    """
    if not statement_table_agent_enabled():
        return None
    q = (question or "").strip()
    fid = (file_id or "").strip()
    if not db or not case_id or not q or not fid:
        return None

    label = (file_label or "").strip() or file_display_name(db, fid)
    session = StatementTableSession(
        case_id=case_id,
        file_id=fid,
        file_label=label,
        question=q,
        db=db if rows is None else None,
        rows=list(rows) if rows is not None else None,
        scope_note=scope_note or "",
    )

    # Fast reject: no transactions in scope.
    if rows is not None and len(rows) == 0:
        return None
    if rows is None and not CaseFileTransactionService.case_has_transactions(
        db, case_id, file_ids=[fid]
    ):
        return None

    user_payload = _build_user_payload(
        question=q,
        file_id=fid,
        file_label=label,
        scope_note=scope_note,
        sql_plan_hints=sql_plan_hints,
        conversation_history=conversation_history,
    )

    try:
        llm = create_legal_llm(
            temperature=0.0,
            max_tokens=_max_tokens(),
            use_rate_limiting=False,
        )
        middleware = _build_middleware()
        agent_kwargs: Dict[str, Any] = {
            "model": llm,
            "tools": build_statement_table_tools() + build_statement_insight_tools(),
            "system_prompt": _SYSTEM_PROMPT,
        }
        if middleware:
            agent_kwargs["middleware"] = middleware
        agent = create_agent(**agent_kwargs)

        with bind_statement_table_session(session):
            result = agent.invoke(
                {
                    "messages": [
                        HumanMessage(content=user_payload),
                    ]
                }
            )
    except Exception as exc:
        logger.warning("[StatementTableAgent] invoke failed: %s", exc)
        return None

    messages = result.get("messages") if isinstance(result, dict) else None
    if not messages:
        return None

    query_used = "query_statement" in session.tool_calls
    insight_used = any(name in session.tool_calls for name in INSIGHT_TOOL_NAMES)
    if not (query_used or insight_used):
        logger.info(
            "[StatementTableAgent] no data tool used case=%s file=%s tools=%s",
            case_id,
            fid,
            session.tool_calls,
        )
        return None

    final_text = _final_ai_text(messages)

    # Analytical/advisory turn: numbers already computed by insight tools; the model
    # only frames them. Prefer this whenever an insight tool ran.
    if insight_used:
        patch = _insight_patch(
            db=db,
            case_id=case_id,
            session=session,
            final_text=final_text,
        )
        if patch is not None:
            logger.info(
                "[StatementTableAgent] insight ok case=%s tools=%s",
                case_id,
                session.tool_calls,
            )
            return patch

    # Pure factual turn: deterministic fact-bound synthesis from query_statement.
    patch = _patch_from_session(
        db=db,
        case_id=case_id,
        session=session,
        question=q,
        conversation_history=conversation_history,
    )
    if patch is None:
        logger.info(
            "[StatementTableAgent] no usable facts after tools case=%s final=%r",
            case_id,
            final_text[:120],
        )
        return None

    logger.info(
        "[StatementTableAgent] ok case=%s op=%s tools=%s",
        case_id,
        patch.get("statement_sql_meta", {}).get("operation"),
        session.tool_calls,
    )
    return patch
