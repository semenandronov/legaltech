"""
LLM planner for bank-statement SQL operations (chat assistant).

Maps a lawyer question → structured plan (operation + period + filters).
Uses the same primary LLM as legal answers (create_legal_llm / Qwen).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

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

ConversationHistory = Sequence[Mapping[str, Any]]


def statement_sql_planner_enabled() -> bool:
    return bool(getattr(config, "STATEMENT_SQL_PLANNER_ENABLED", True))


def _planner_min_confidence() -> float:
    return max(
        0.0,
        min(1.0, float(getattr(config, "STATEMENT_SQL_PLANNER_MIN_CONF", 0.65) or 0.65)),
    )


def _history_turn_limit() -> int:
    return max(2, int(getattr(config, "OPERATIONS_CHAT_HISTORY_MAX_TURNS", 6) or 6))


def format_statement_sql_conversation_history(
    history: ConversationHistory | None,
    *,
    max_turns: Optional[int] = None,
) -> str:
    """Compact dialogue context for planner / synthesis (role-tagged lines)."""
    if not history:
        return ""
    turn_limit = max_turns if max_turns is not None else _history_turn_limit()
    max_items = max(2, turn_limit * 2)
    lines: List[str] = []
    for item in list(history)[-max_items:]:
        role = str(item.get("role") or "").strip().lower()
        content = " ".join(str(item.get("content") or "").split()).strip()
        if not content:
            continue
        if role == "user":
            label = "Пользователь"
        elif role == "assistant":
            label = "Ассистент"
        else:
            continue
        if len(content) > 500:
            content = content[:497] + "…"
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


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
    conversation_history: ConversationHistory | None = None,
) -> str:
    """
    Build planner prompt from current question + dialogue history only.

    prior_turn_state / sql_plan_hints are accepted for call-site compatibility but are
    intentionally NOT injected into the prompt — structured prior filters biased the
    model into keeping stale amount thresholds. Continuity for underspecified follow-ups
    is applied after planning via apply_sql_plan_hints (file/period/counterparty).
    """
    del sql_plan_hints, prior_turn_state  # not shown to the model
    scope = ", ".join(scope_file_ids) or "[все выписки дела]"
    history_text = format_statement_sql_conversation_history(conversation_history)
    history_block = ""
    if history_text:
        history_block = (
            "Предыдущий диалог по этой выписке:\n"
            f"{history_text}\n\n"
        )
    return (
        "Составь план SQL-запроса к таблице операций банковской выписки.\n"
        "Опирайся на текущий вопрос и предыдущий диалог: сам реши, какие фильтры нужны.\n\n"
        "Схема таблицы операций (одна доменная таблица):\n"
        "- description / row_columns — текст назначения платежа и колонки PDF "
        "(контрагент, магазин, назначение). Сюда относится description_contains.\n"
        "- amount_rub — сумма операции (знак: >0 поступление, <0 списание).\n"
        "- operation_date / operation_datetime_text — дата и время операции.\n\n"
        "operation=count — только число операций («сколько операций»), без дат и списка.\n"
        "operation=sum — «общая сумма», «итого списаний/поступлений».\n"
        "amount_semantics=credit для поступлений/приходов; debit для списаний/расходов; "
        "any для общей суммы без направления. Не клади «списаний/поступлений» в description_contains.\n"
        "operation=list — «перечисли операции», «покажи все за период», "
        "а также «сколько и в какие даты» / «какие даты» (нужны и число, и строки с датами).\n"
        "operation=find — «операция 11.06.2026 в 19:28», «что было в этот день».\n"
        "operation=top — «самая крупная», «топ-5», «крупнейшие по сумме» "
        "(сортировка по |amount|; result_limit=1 для одной крупнейшей, иначе 5/N).\n"
        "operation=group — «основные контрагенты», «повторяющиеся платежи» "
        "(группировка по description; result_limit по умолчанию 10).\n"
        "group_order=abs_sum для контрагентов по обороту; group_order=count для повторяющихся/частых.\n"
        "group_min_count=2 для «повторяющиеся»; иначе пусто.\n"
        "result_limit — только для top/group (число N). Для остальных оставь пустым.\n\n"
        "description_contains — только значимый фрагмент из вопроса или явного продолжения "
        "диалога (имя контрагента/сервиса/назначения, например Yandex, Иванов). "
        "НЕ пиши туда служебные слова: «операций», «сколько», «платежей», «покажи».\n\n"
        "amount_compare / amount_min / amount_max — только если порог суммы есть в текущем "
        "вопросе или вопрос явно продолжает тот же срез («из них», «эти же»). "
        "Иначе оставь пустыми.\n\n"
        "Даты ТОЛЬКО в формате DD.MM.YYYY.\n"
        "Для периода (месяц, квартал, диапазон): date_from + date_to, on_date ОБЯЗАТЕЛЬНО пустой.\n"
        "Для «май 2026» / «в мае» → date_from=01.05.2026, date_to=31.05.2026, on_date=\"\".\n"
        "on_date заполняй ТОЛЬКО если вопрос про один конкретный день (11.06.2026), не про месяц целиком.\n"
        "Для «в мае» без года — год из вопроса или 2026.\n"
        "time_hint — только время из вопроса (19:28).\n\n"
        "Недосказанные уточнения («а сумма?», «на какие суммы», «подробнее», «только списания») "
        "читай из предыдущего диалога и сохрани релевантный scope. "
        "Самодостаточный новый вопрос строй заново по его тексту.\n\n"
        "statement_file_id — id выписки из каталога, если в scope одна выписка — можно оставить пустым.\n\n"
        f"SQL-scope file_id: {scope}\n\n"
        f"{history_block}"
        f"Каталог файлов:\n{_format_catalog(catalog)}\n\n"
        f"Текущий вопрос юриста:\n{question.strip()}\n"
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
    conversation_history: ConversationHistory | None = None,
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
        conversation_history=conversation_history,
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
