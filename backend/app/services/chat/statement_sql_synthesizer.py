"""
LLM synthesis of user-facing answers from SQL facts.

The executor returns only structured data; this module is the sole source of chat text
(except a minimal deterministic fallback when the model is unavailable).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.services.chat.statement_sql_executor import StatementSqlExecutionResult
from app.services.chat.statement_sql_facts import (
    build_facts_evidence_block,
    compose_fallback_answer,
)
from app.services.chat.statement_sql_models import StatementSqlPlan

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StatementSqlSynthesisResult:
    text: str
    via_llm: bool

_PIPE_ROW_RE = re.compile(r"\|\s*#\d+\s*\|", re.IGNORECASE)


def statement_sql_synthesis_enabled() -> bool:
    return bool(getattr(config, "STATEMENT_SQL_SYNTHESIS_ENABLED", True))


def _synthesis_model_uri() -> str:
    explicit = (getattr(config, "STATEMENT_SQL_SYNTHESIS_MODEL", None) or "").strip()
    if explicit:
        return explicit
    from app.services.chat.case_query_planner import draft_generation_model_uri

    return draft_generation_model_uri()


def _operation_instructions(operation: str) -> str:
    if operation == "count":
        return (
            "Пользователь спрашивает о количестве операций. Дай число и период; "
            "сумму указывай только если это уместно по вопросу. "
            "Не перечисляй отдельные операции и не копируй технические строки."
        )
    if operation == "sum":
        return (
            "Пользователь спрашивает об итоговой сумме. Укажи сумму, период и при необходимости "
            "количество операций. Не перечисляй строки выписки."
        )
    if operation == "list":
        return (
            "Пользователь просит список операций. Кратко перечисли найденные операции "
            "(дата, сумма, назначение). Если список обрезан — скажи об этом."
        )
    if operation == "find":
        return (
            "Пользователь ищет конкретную операцию. Ответь точно по найденным строкам: "
            "дата/время, сумма, назначение."
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
) -> StatementSqlSynthesisResult:
    """
    Formulate a natural-language answer from SQL facts.

    Uses a fast draft model by default. On failure returns a minimal fallback
    (never raw executor templates or pipe-formatted rows for count/sum).
    """
    facts = execution.facts
    if facts is None:
        return StatementSqlSynthesisResult(text="", via_llm=False)

    if not statement_sql_synthesis_enabled():
        return StatementSqlSynthesisResult(
            text=compose_fallback_answer(question=question, plan=plan, facts=facts),
            via_llm=False,
        )

    evidence = build_facts_evidence_block(question=question, plan=plan, facts=facts)
    op_hint = _operation_instructions(facts.operation)

    try:
        from app.services.llm_factory import create_llm

        max_tokens = max(
            256,
            int(getattr(config, "STATEMENT_SQL_SYNTHESIS_MAX_TOKENS", 1024) or 1024),
        )
        llm = create_llm(
            model=_synthesis_model_uri(),
            temperature=0.15,
            max_tokens=max_tokens,
            use_rate_limiting=False,
            cache_enabled=False,
        )
        resp = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "Ты юридический ассистент по банковским выпискам в деле. "
                        "Сформулируй ответ на вопрос пользователя по предоставленным фактам из SQL. "
                        "Пиши по-русски, кратко и по делу, как коллеге-юристу. "
                        "Не выдумывай суммы, даты и операции. "
                        "Не используй технический формат «файл | #N | …» и не копируй сырой дамп строк. "
                        "Не начинай с «По справке» — формулируй естественно под вопрос."
                    )
                ),
                HumanMessage(
                    content=(
                        f"ИНСТРУКЦИЯ ПО ТИПУ ЗАПРОСА:\n{op_hint}\n\n"
                        f"ФАКТЫ ИЗ БАЗЫ:\n{evidence}\n\n"
                        f"ВОПРОС:\n{question.strip()}\n\n"
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
