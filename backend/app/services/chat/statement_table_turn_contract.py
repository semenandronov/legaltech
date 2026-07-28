"""
Turn contract for the statement table agent.

Classifies the lawyer's question, checks that tool usage matches intent, and
runs a deterministic repair (grounded SQL / counterparty profile) when the model
picked the wrong tool — without a second guess from the LLM.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_analytics import compute_counterparty_profile, format_amount_rub
from app.services.chat.statement_entity_grounding import (
    entity_needle_candidates,
    ground_counterparty_needle,
    stem_probe_variants,
)
from app.services.chat.statement_lawyer_tool_registry import (
    ANALYTICAL_LAWYER_TOOL_NAMES,
    ENTITY_LAWYER_TOOL_NAMES,
    QUERY_LAWYER_TOOL_NAMES,
)

_LEGACY_INSIGHT = frozenset(
    {
        "statement_overview",
        "monthly_breakdown",
        "detect_anomalies",
        "counterparty_profile",
        "suspicion_period_analysis",
        "category_breakdown",
        "inspect_statement",
        "probe_description",
    }
)
_LEGACY_QUERY = frozenset({"query_statement", "transactions_query", "evidence_bundle"})
_LEGACY_ENTITY = frozenset({"counterparty_profile", "counterparty_dossier", "resolve_entity"})
_WHOLE_STATEMENT_TOOLS = (
    (ANALYTICAL_LAWYER_TOOL_NAMES - ENTITY_LAWYER_TOOL_NAMES)
    | frozenset(
        {
            "statement_overview",
            "monthly_breakdown",
            "detect_anomalies",
            "category_breakdown",
            "suspicion_period_analysis",
            "inspect_statement",
            "flow_profile",
            "risk_scan",
            "legal_calendar",
            "statement_context",
        }
    )
)

from app.services.chat.statement_sql_executor import (
    execute_statement_sql_plan,
    execute_statement_sql_plan_on_rows,
)
from app.services.chat.statement_sql_facts import compose_fallback_answer
from app.services.chat.statement_sql_models import StatementSqlPlan
from app.services.chat.statement_sql_plan_normalize import normalize_statement_sql_plan
from app.services.chat.statement_sql_value_grounding import (
    DbDescriptionMatchProbe,
    RowsDescriptionMatchProbe,
    _best_grounded_token,
    refine_plan_with_db,
    refine_plan_with_rows,
)
from app.services.chat.statement_sql_plan_validate import extract_content_tokens
from app.services.chat.statement_table_session import StatementTableSession

logger = logging.getLogger(__name__)

StatementTurnIntent = Literal[
    "open_analytics",
    "counterparty_lookup",
    "factual_aggregate",
    "factual_list",
    "unknown",
]

_FIO_RE = re.compile(
    r"\b[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.[А-ЯЁ]\."
)
_ORG_RE = re.compile(
    r"\b(?:ООО|АО|ПАО|ИП|ЗАО|НАО)\s+\"?[А-ЯЁA-Za-z0-9][^,\n\"]{2,80}\"?",
    re.IGNORECASE,
)
_OPEN_ANALYTICS_RE = re.compile(
    r"\b("
    r"что\s+в\s+выписк|на\s+что\s+смотрет|помоги\s+разобра|"
    r"подозрительн\w*|аномал\w*|вывод\s+актив|риск\w*|общ(ий|ая)\s+обзор|"
    r"динамик\w*|по\s+месяц|категори\w*"
    r")\b",
    re.IGNORECASE,
)
_COUNTERPARTY_CUE_RE = re.compile(
    r"\b("
    r"операци\w*\s+(с|по)\s+|"
    r"были\s+ли|есть\s+ли|нашли\s+ли|"
    r"перевод\w*\s+(для|от|к|на)\s+|"
    r"контрагент|плательщик|получател"
    r")\b",
    re.IGNORECASE,
)
_AGGREGATE_RE = re.compile(
    r"\b("
    r"топ[-\s]?\d+|"
    r"сам(ая|ый|ое)\s+крупн|"
    r"сколько\s+операц|"
    r"число\s+операц|"
    r"сумм(а|арн)|"
    r"оборот|"
    r"основн\w+\s+(контрагент|групп)|"
    r"крупнейш"
    r")\b",
    re.IGNORECASE,
)
_LIST_RE = re.compile(
    r"\b(список|перечисли|покажи\s+все|все\s+операц|найди\s+операц)\b",
    re.IGNORECASE,
)

_ENTITY_INSIGHT_TOOLS = ENTITY_LAWYER_TOOL_NAMES | frozenset({"counterparty_profile"})
_WHOLE_STATEMENT_INSIGHT_TOOLS = _WHOLE_STATEMENT_TOOLS


def classify_statement_turn_intent(question: str) -> StatementTurnIntent:
    q = (question or "").strip()
    if not q:
        return "unknown"
    if _OPEN_ANALYTICS_RE.search(q):
        return "open_analytics"
    if _AGGREGATE_RE.search(q) and not _COUNTERPARTY_CUE_RE.search(q):
        return "factual_aggregate"
    if _LIST_RE.search(q):
        return "factual_list"
    if _FIO_RE.search(q) or _ORG_RE.search(q):
        return "counterparty_lookup"
    if _COUNTERPARTY_CUE_RE.search(q):
        return "counterparty_lookup"
    return "unknown"


def _plan_addresses_needle(plan: Optional[StatementSqlPlan], needle: str) -> bool:
    if not plan or not needle:
        return False
    desc = (plan.description_contains or "").strip().lower()
    needle_l = needle.lower()
    if not desc:
        return False
    return desc == needle_l or desc in needle_l or needle_l in desc


def _aggregate_top_limit(question: str) -> Optional[int]:
    m = re.search(r"топ[-\s]?(\d+)", question or "", re.IGNORECASE)
    if not m:
        return None
    try:
        return max(1, min(50, int(m.group(1))))
    except ValueError:
        return None


@dataclass(frozen=True)
class StatementTurnOutcome:
    intent: StatementTurnIntent
    accept_insight_path: bool
    accept_query_path: bool
    needs_deterministic_repair: bool
    repair_reason: str = ""


def assess_statement_turn_outcome(
    *,
    question: str,
    session: StatementTableSession,
) -> StatementTurnOutcome:
    intent = classify_statement_turn_intent(question)
    tools = set(session.tool_calls)
    query_used = bool(tools & (_LEGACY_QUERY | QUERY_LAWYER_TOOL_NAMES))
    insight_used = bool(tools & (ANALYTICAL_LAWYER_TOOL_NAMES | _LEGACY_INSIGHT))
    entity_insight = bool(tools & _ENTITY_INSIGHT_TOOLS)
    whole_insight_only = insight_used and not entity_insight and not query_used

    needle = ""
    if intent == "counterparty_lookup":
        rows = list(session.rows) if session.rows is not None else None
        needle = ground_counterparty_needle(
            question,
            rows=rows,
            db=session.db,
            case_id=session.case_id,
            file_id=session.file_id,
        )

    if intent == "counterparty_lookup":
        if entity_insight or _plan_addresses_needle(session.last_plan, needle):
            return StatementTurnOutcome(
                intent=intent,
                accept_insight_path=entity_insight,
                accept_query_path=query_used,
                needs_deterministic_repair=False,
            )
        if whole_insight_only or (
            query_used
            and needle
            and not _plan_addresses_needle(session.last_plan, needle)
            and session.last_plan is not None
            and session.last_plan.operation in {"count", "sum"}
        ):
            return StatementTurnOutcome(
                intent=intent,
                accept_insight_path=False,
                accept_query_path=False,
                needs_deterministic_repair=True,
                repair_reason="counterparty_missed",
            )
        if needle and not query_used and not entity_insight:
            return StatementTurnOutcome(
                intent=intent,
                accept_insight_path=False,
                accept_query_path=False,
                needs_deterministic_repair=True,
                repair_reason="counterparty_no_entity_tool",
            )

    if intent == "factual_aggregate":
        top_n = _aggregate_top_limit(question)
        group_ok = (
            session.last_plan is not None
            and session.last_plan.operation == "group"
            and session.last_facts is not None
            and bool(session.last_facts.group_rows)
        )
        overview_ok = (
            "statement_overview" in tools
            or "flow_profile" in tools
            or group_ok
        )
        if whole_insight_only and top_n and not overview_ok:
            return StatementTurnOutcome(
                intent=intent,
                accept_insight_path=False,
                accept_query_path=False,
                needs_deterministic_repair=True,
                repair_reason="aggregate_wrong_tool",
            )
        if query_used and group_ok:
            return StatementTurnOutcome(
                intent=intent,
                accept_insight_path=False,
                accept_query_path=True,
                needs_deterministic_repair=False,
            )
        if insight_used and overview_ok:
            return StatementTurnOutcome(
                intent=intent,
                accept_insight_path=True,
                accept_query_path=False,
                needs_deterministic_repair=False,
            )

    if intent == "open_analytics" and insight_used:
        return StatementTurnOutcome(
            intent=intent,
            accept_insight_path=True,
            accept_query_path=query_used,
            needs_deterministic_repair=False,
        )

    return StatementTurnOutcome(
        intent=intent,
        accept_insight_path=insight_used,
        accept_query_path=query_used,
        needs_deterministic_repair=False,
    )


def _execute_plan_on_session(
    session: StatementTableSession,
    plan: StatementSqlPlan,
    question: str,
):
    plan = normalize_statement_sql_plan(plan, question)
    if session.uses_in_memory_rows:
        plan = refine_plan_with_rows(
            plan,
            question=question,
            rows=list(session.rows or []),
        )
        return execute_statement_sql_plan_on_rows(
            plan=plan,
            rows=list(session.rows or []),
            file_id=session.file_id,
            file_label=session.file_label,
            question=question,
            scope_note=session.scope_note,
        )
    assert session.db is not None
    plan = refine_plan_with_db(
        session.db,
        case_id=session.case_id,
        plan=plan,
        question=question,
        file_id=session.file_id,
    )
    return execute_statement_sql_plan(
        session.db,
        case_id=session.case_id,
        plan=plan,
        scope_file_ids=[session.file_id],
        question=question,
    )


def _counterparty_answer(
    session: StatementTableSession,
    *,
    needle: str,
    profile,
    question: str,
) -> str:
    label = session.file_label or "выписке"
    scope = f"{session.scope_note.strip()} " if session.scope_note.strip() else ""
    if not profile.matched or profile.op_count == 0:
        return (
            f"{scope}По файлу «{label}» операций с «{needle}» не найдено."
        ).strip()

    q_l = (question or "").lower()
    yes_no = bool(
        re.search(r"\b(были\s+ли|есть\s+ли|нашли\s+ли)\b", q_l)
    )
    period = ""
    if profile.date_min and profile.date_max:
        period = (
            f" за период {profile.date_min.strftime('%d.%m.%Y')}"
            f" — {profile.date_max.strftime('%d.%m.%Y')}"
        )
    summary = (
        f"{profile.op_count} операций{period}; поступления "
        f"{format_amount_rub(profile.inflow_sum)}, списания "
        f"{format_amount_rub(profile.outflow_sum)}, сальдо "
        f"{format_amount_rub(profile.net_sum)}."
    )
    if yes_no:
        lead = f"Да, по файлу «{label}» есть операции с «{needle}»: {summary}"
    else:
        lead = f"По файлу «{label}» по «{needle}»: {summary}"
    return f"{scope}{lead}".strip()


def repair_statement_turn(
    *,
    db: Session,
    case_id: str,
    session: StatementTableSession,
    question: str,
    outcome: StatementTurnOutcome,
) -> Optional[dict]:
    """Deterministic repair when the agent chose tools that do not match intent."""
    del case_id
    if not outcome.needs_deterministic_repair:
        return None

    rows = list(session.rows) if session.rows is not None else session.load_all_rows()

    if outcome.intent == "counterparty_lookup":
        needle = ground_counterparty_needle(
            question,
            rows=rows,
            db=session.db,
            case_id=session.case_id,
            file_id=session.file_id,
        )
        profile = compute_counterparty_profile(rows, needle) if needle else None
        if not needle:
            answer = (
                f"По файлу «{session.file_label or 'выписке'}» не удалось сопоставить "
                "имя или контрагента из вопроса с текстом операций. "
                "Уточните фамилию или фрагмент назначения платежа."
            )
            return _repair_patch(db, session, answer=answer, operation="counterparty_lookup")
        assert profile is not None
        if profile.matched:
            session.add_citation_rows(profile.rows[:20])
        answer = _counterparty_answer(session, needle=needle, profile=profile, question=question)
        logger.info(
            "[StatementTableTurn] repair counterparty file=%s needle=%r ops=%s reason=%s",
            session.file_id,
            needle,
            profile.op_count,
            outcome.repair_reason,
        )
        return _repair_patch(
            db,
            session,
            answer=answer,
            operation="counterparty_lookup",
            row_count=profile.op_count,
        )

    if outcome.intent == "factual_aggregate":
        top_n = _aggregate_top_limit(question) or 5
        plan = StatementSqlPlan(
            operation="group",
            statement_file_id=session.file_id,
            result_limit=str(top_n),
            group_order="abs_sum",
            confidence=1.0,
            rationale="turn_contract_repair",
        )
        execution = _execute_plan_on_session(session, plan, question)
        if not execution.resolved or execution.facts is None:
            return None
        session.last_plan = plan
        session.last_facts = execution.facts
        session.last_execution = execution
        if execution.rows:
            session.add_citation_rows(execution.rows[:20])
        answer = compose_fallback_answer(question=question, plan=plan, facts=execution.facts)
        logger.info(
            "[StatementTableTurn] repair aggregate file=%s groups=%s reason=%s",
            session.file_id,
            len(execution.facts.group_rows),
            outcome.repair_reason,
        )
        return _repair_patch(
            db,
            session,
            answer=answer,
            operation="group",
            row_count=execution.facts.row_count,
        )

    return None


def _repair_patch(
    db: Session,
    session: StatementTableSession,
    *,
    answer: str,
    operation: str,
    row_count: int = 0,
    resolver: str = "table_agent_repair",
) -> dict:
    from langchain_core.messages import AIMessage

    from app.services.chat.conversation_turn_state import ConversationTurnState

    citations: List[dict] = []
    if session.citation_rows and db is not None:
        from app.services.chat.case_transaction_graph import build_transaction_citations

        citations = build_transaction_citations(
            db,
            case_id=session.case_id,
            rows=session.citation_rows[:20],
        )

    outbound = ConversationTurnState(
        domain="statement_analytics",
        statement_file_id=session.file_id,
        operation=operation,
        description_contains=(session.last_plan.description_contains if session.last_plan else ""),
        structured_data_plane="sql",
        topic_file_ids=(session.file_id,),
    ).to_dict()

    return {
        "transaction_agent_resolved": True,
        "response": answer.strip(),
        "messages": [AIMessage(content=answer.strip())],
        "citations": citations,
        "outbound_turn_state": outbound,
        "statement_sql_meta": {
            "resolver": resolver,
            "operation": operation,
            "row_count": row_count,
            "file_id": session.file_id,
            "tool_calls": list(session.tool_calls),
            "repair_reason": operation,
        },
    }
