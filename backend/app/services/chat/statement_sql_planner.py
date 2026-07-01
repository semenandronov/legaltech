"""
LLM planner for bank-statement SQL operations (chat assistant).

Maps a lawyer question → structured plan (operation + period + filters).
Uses the same primary LLM as legal answers (create_legal_llm / Qwen).
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.models.case import File as CaseFile
from app.services.chat.statement_sql_models import (
    StatementSqlPlan,
    StatementSqlPlanResult,
)
from app.services.chat.statement_sql_plan_normalize import (
    apply_amount_semantics_normalization,
    apply_sql_plan_hints,
    normalize_statement_sql_plan,
)
from app.services.chat.structured_data_router import (
    StatementFileCatalogEntry,
    build_statement_file_catalog,
)

logger = logging.getLogger(__name__)


def statement_sql_planner_enabled() -> bool:
    return bool(getattr(config, "STATEMENT_SQL_PLANNER_ENABLED", True))


def _planner_min_confidence() -> float:
    return max(
        0.0,
        min(1.0, float(getattr(config, "STATEMENT_SQL_PLANNER_MIN_CONF", 0.65) or 0.65)),
    )


def _format_catalog(catalog: Sequence[StatementFileCatalogEntry]) -> str:
    if not catalog:
        return "[нет файлов]"
    lines: List[str] = []
    for entry in catalog:
        sql_flag = "да" if entry.has_sql_table else "нет"
        lines.append(
            f"- id={entry.file_id} | {entry.filename} | тип={entry.doc_type} | SQL={sql_flag}"
        )
    return "\n".join(lines)


def _build_planner_prompt(
    *,
    question: str,
    catalog: Sequence[StatementFileCatalogEntry],
    scope_file_ids: Sequence[str],
    sql_plan_hints: Optional[dict] = None,
    prior_turn_state: Optional[dict] = None,
) -> str:
    scope = ", ".join(scope_file_ids) or "[все выписки дела]"
    hints_block = ""
    if sql_plan_hints or prior_turn_state:
        parts: List[str] = []
        if prior_turn_state:
            parts.append(f"Prior turn state: {prior_turn_state}")
        if sql_plan_hints:
            parts.append(f"Structured hints (apply when question is underspecified): {sql_plan_hints}")
        hints_block = "\n".join(parts) + "\n\n"
    return (
        "Составь план SQL-запроса к таблице операций банковской выписки.\n\n"
        "operation=count — «сколько операций», «количество платежей».\n"
        "operation=sum — «общая сумма», «итого списаний/поступлений».\n"
        "amount_semantics=credit для поступлений/приходов; debit для списаний/расходов; "
        "any для общей суммы без направления. Не клади «списаний/поступлений» в description_contains.\n"
        "operation=list — «перечисли операции», «покажи все за период».\n"
        "operation=find — «операция 11.06.2026 в 19:28», «что было в этот день».\n\n"
        "Даты ТОЛЬКО в формате DD.MM.YYYY.\n"
        "Для периода (месяц, квартал, диапазон): date_from + date_to, on_date ОБЯЗАТЕЛЬНО пустой.\n"
        "Для «май 2026» / «в мае» → date_from=01.05.2026, date_to=31.05.2026, on_date=\"\".\n"
        "on_date заполняй ТОЛЬКО если вопрос про один конкретный день (11.06.2026), не про месяц целиком.\n"
        "Для «в мае» без года — год из вопроса или 2026.\n"
        "time_hint — только время из вопроса (19:28).\n\n"
        "statement_file_id — id выписки из каталога, если в scope одна выписка — можно оставить пустым.\n\n"
        f"SQL-scope file_id: {scope}\n\n"
        f"{hints_block}"
        f"Каталог файлов:\n{_format_catalog(catalog)}\n\n"
        f"Вопрос юриста:\n{question.strip()}\n"
    )


def _invoke_planner(prompt: str) -> StatementSqlPlan | None:
    if not statement_sql_planner_enabled():
        return None
    try:
        from app.services.llm_factory import create_legal_llm
        from app.services.observability.assistant_pipeline_langfuse_tracing import assistant_step_span
        from app.services.observability.langfuse_service import get_langchain_callbacks

        max_tokens = int(getattr(config, "STATEMENT_SQL_PLANNER_MAX_TOKENS", 512) or 512)
        llm = create_legal_llm(temperature=0.0, max_tokens=max_tokens, use_rate_limiting=False)
        structured = llm.with_structured_output(StatementSqlPlan)
        callbacks = get_langchain_callbacks(tags=["assistant", "statement_sql_planner"])

        with assistant_step_span(
            "case",
            "statement_sql_planner",
            input_payload={"prompt_chars": len(prompt)},
        ) as span_out:
            plan: StatementSqlPlan = structured.invoke(
                [
                    SystemMessage(
                        content=(
                            "Ты планировщик SQL-запросов к банковским выпискам для юриста. "
                            "Верни точный период и тип операции. Не выдумывай даты."
                        )
                    ),
                    HumanMessage(content=prompt),
                ],
                config={"callbacks": callbacks} if callbacks else None,
            )
            span_out["operation"] = plan.operation
            span_out["confidence"] = float(plan.confidence or 0.0)
        return plan
    except Exception as exc:
        logger.warning("[StatementSqlPlanner] LLM failed: %s", exc)
        return None


def _resolve_target_file_id(
    plan: StatementSqlPlan,
    scope_file_ids: Sequence[str],
) -> Optional[str]:
    allowed = {str(fid).strip() for fid in scope_file_ids if str(fid).strip()}
    if not allowed:
        return None
    chosen = (plan.statement_file_id or "").strip()
    if chosen and chosen in allowed:
        return chosen
    if len(allowed) == 1:
        return next(iter(allowed))
    return None


def plan_statement_sql(
    db,
    *,
    case_id: str,
    question: str,
    scope_file_ids: Sequence[str],
    attached_file_ids: Optional[Sequence[str]] = None,
    sql_plan_hints: Optional[dict] = None,
    prior_turn_state: Optional[dict] = None,
) -> StatementSqlPlanResult:
    """Produce an executable SQL plan or None when planner is disabled / uncertain."""
    q = (question or "").strip()
    scope = [str(fid).strip() for fid in scope_file_ids if str(fid).strip()]
    if not q or not scope:
        return StatementSqlPlanResult(plan=None, resolver="disabled", reason="empty_scope")

    if not statement_sql_planner_enabled():
        return StatementSqlPlanResult(plan=None, resolver="disabled", reason="planner_disabled")

    catalog = build_statement_file_catalog(
        db,
        case_id=case_id,
        attached_file_ids=attached_file_ids or scope,
    )
    prompt = _build_planner_prompt(
        question=q,
        catalog=catalog,
        scope_file_ids=scope,
        sql_plan_hints=sql_plan_hints,
        prior_turn_state=prior_turn_state,
    )
    raw = _invoke_planner(prompt)
    if raw is None:
        return StatementSqlPlanResult(plan=None, resolver="llm_failed", reason="llm_failed")

    conf = max(0.0, min(1.0, float(raw.confidence or 0.0)))
    if conf < _planner_min_confidence():
        return StatementSqlPlanResult(
            plan=None,
            resolver="low_confidence",
            reason=(raw.rationale or "low_confidence")[:200],
        )

    target = _resolve_target_file_id(raw, scope)
    if not target:
        return StatementSqlPlanResult(
            plan=None,
            resolver="low_confidence",
            reason="ambiguous_statement_file",
        )

    plan = normalize_statement_sql_plan(
        raw.model_copy(update={"statement_file_id": target, "confidence": conf}),
        q,
    )
    plan = apply_sql_plan_hints(plan, sql_plan_hints)
    plan = apply_amount_semantics_normalization(plan, q)
    logger.info(
        "[StatementSqlPlanner] case=%s op=%s file=%s conf=%.2f period=%s..%s on=%s",
        case_id,
        plan.operation,
        target,
        conf,
        plan.date_from or "—",
        plan.date_to or "—",
        plan.on_date or "—",
    )
    return StatementSqlPlanResult(plan=plan, resolver="llm", reason=plan.rationale or "ok")


def file_display_name(db, file_id: str) -> str:
    if not db or not file_id:
        return file_id or "выписка"
    row = db.query(CaseFile).filter(CaseFile.id == file_id).first()
    return row.filename if row and row.filename else file_id
