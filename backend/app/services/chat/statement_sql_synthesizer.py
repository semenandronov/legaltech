"""
LLM synthesis of user-facing answers from SQL facts.

Aggregate ops (count/sum/top/group) use deterministic compose — numbers never
come from dialogue history. list/find may use LLM with hard fact-binding.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.services.chat.statement_sql_executor import StatementSqlExecutionResult
from app.services.chat.statement_sql_facts import (
    build_facts_evidence_block,
    compose_fallback_answer,
)
from app.services.chat.statement_sql_models import StatementSqlPlan
from app.services.chat.statement_sql_planner import format_statement_sql_conversation_history

logger = logging.getLogger(__name__)

ConversationHistory = Sequence[Mapping[str, object]]

_DETERMINISTIC_OPS = frozenset({"count", "sum", "top", "group"})
_PIPE_ROW_RE = re.compile(r"\|\s*#\d+\s*\|", re.IGNORECASE)


@dataclass(frozen=True)
class StatementSqlSynthesisResult:
    text: str
    via_llm: bool


def statement_sql_synthesis_enabled() -> bool:
    return bool(getattr(config, "STATEMENT_SQL_SYNTHESIS_ENABLED", True))


def _synthesis_model_uri() -> str:
    explicit = (getattr(config, "STATEMENT_SQL_SYNTHESIS_MODEL", None) or "").strip()
    if explicit:
        return explicit
    from app.services.chat.case_query_planner import draft_generation_model_uri

    return draft_generation_model_uri()


def _readability_instructions() -> str:
    return (
        "Оформи ответ так, чтобы юристу было удобно читать: сначала короткий итог по вопросу, "
        "затем детали. Структуру выбери сам (абзацы, нумерованный или маркированный список, "
        "при необходимости раздели поступления и списания). "
        "Не вываливай всё в одну строку. Не добавляй служебные фразы про «ответ сформирован по таблице»."
    )


def _operation_instructions(operation: str) -> str:
    if operation == "list":
        return (
            "Пользователь просит список операций (в т.ч. «сколько и в какие даты»). "
            "Сначала укажи точное количество из фактов, затем перечисли все операции из блока фактов "
            "(дата, сумма, назначение), ничего не пропускай и ничего не добавляй. "
            "Если в фактах указано, что выборка обрезана — скажи об этом и назови показанное число строк."
        )
    if operation == "find":
        return (
            "Пользователь ищет конкретную операцию. Ответь по всем найденным строкам из фактов: "
            "дата/время, сумма, назначение. Ничего не опускай и не добавляй."
        )
    return "Ответь строго по фактам из данных выписки."


def _sanitize_llm_output(text: str) -> str:
    """Reject outputs that look like debug row dumps."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    if _PIPE_ROW_RE.search(cleaned):
        return ""
    if "файл:" in cleaned.lower() and "| #" in cleaned:
        return ""
    return cleaned


def build_sql_evidence_block(
    *,
    question: str,
    plan: StatementSqlPlan,
    execution: StatementSqlExecutionResult,
) -> str:
    """Evidence block for hybrid synthesis or logging."""
    facts = execution.facts
    if facts is None:
        return ""
    return build_facts_evidence_block(question=question, plan=plan, facts=facts)


def synthesize_statement_sql_answer(
    *,
    question: str,
    plan: StatementSqlPlan,
    execution: StatementSqlExecutionResult,
    conversation_history: Optional[ConversationHistory] = None,
) -> StatementSqlSynthesisResult:
    """
    Formulate a natural-language answer from SQL facts.

    count/sum/top/group → deterministic (fact-bound).
    list/find → LLM with fact-binding; fallback to deterministic on failure.
    """
    facts = execution.facts
    if facts is None:
        return StatementSqlSynthesisResult(text="", via_llm=False)

    if facts.operation in _DETERMINISTIC_OPS or not statement_sql_synthesis_enabled():
        return StatementSqlSynthesisResult(
            text=compose_fallback_answer(question=question, plan=plan, facts=facts),
            via_llm=False,
        )

    evidence = build_facts_evidence_block(question=question, plan=plan, facts=facts)
    op_hint = _operation_instructions(facts.operation)
    readability_hint = _readability_instructions()
    history_text = format_statement_sql_conversation_history(conversation_history)
    history_block = (
        f"ПРЕДЫДУЩИЙ ДИАЛОГ (только контекст уточнения; НЕ источник чисел):\n{history_text}\n\n"
        if history_text
        else ""
    )

    try:
        from app.services.llm_factory import create_llm

        max_tokens = max(
            256,
            int(getattr(config, "STATEMENT_SQL_SYNTHESIS_MAX_TOKENS", 1024) or 1024),
        )
        llm = create_llm(
            model=_synthesis_model_uri(),
            temperature=0.1,
            max_tokens=max_tokens,
            use_rate_limiting=False,
            cache_enabled=False,
        )
        resp = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "Ты юридический ассистент по банковским выпискам в деле. "
                        "Сформулируй ответ на вопрос пользователя ТОЛЬКО по блоку «ФАКТЫ ИЗ БАЗЫ». "
                        "Любые количества, суммы и даты бери исключительно из фактов. "
                        "Если в предыдущем диалоге были другие цифры — игнорируй их. "
                        "Не выдумывай операции, которых нет в фактах. "
                        "Пиши по-русски, кратко и по делу. "
                        f"{readability_hint} "
                        "Не используй технический формат «файл | #N | …». "
                        "Не начинай с «По справке»."
                    )
                ),
                HumanMessage(
                    content=(
                        f"ИНСТРУКЦИЯ ПО ТИПУ ЗАПРОСА:\n{op_hint}\n\n"
                        f"ОФОРМЛЕНИЕ:\n{readability_hint}\n\n"
                        f"{history_block}"
                        f"ФАКТЫ ИЗ БАЗЫ (единственный источник чисел):\n{evidence}\n\n"
                        f"ТЕКУЩИЙ ВОПРОС:\n{question.strip()}\n\n"
                        "Ответ (только текст для пользователя):"
                    )
                ),
            ]
        )
        text = resp.content if hasattr(resp, "content") else str(resp)
        sanitized = _sanitize_llm_output(str(text or ""))
        if sanitized:
            return StatementSqlSynthesisResult(text=sanitized, via_llm=True)
        logger.warning("[StatementSqlSynthesis] LLM returned empty or debug-like output")
    except Exception as exc:
        logger.warning("[StatementSqlSynthesis] LLM failed: %s", exc)

    return StatementSqlSynthesisResult(
        text=compose_fallback_answer(question=question, plan=plan, facts=facts),
        via_llm=False,
    )
