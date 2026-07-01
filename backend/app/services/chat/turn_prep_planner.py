"""
Unified HTTP prep planner: one structured LLM call for turn context + SQL/RAG routing.

Replaces sequential turn_context LLM judge + structured_data_router when enabled.
Falls back to legacy multi-call path on disable or LLM failure.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.config import config
from app.services.chat.referential_classifier import ReferentialKind, classify_referential_kind
from app.services.chat.referential_llm_judge import (
    ReferentialJudgeResult,
    ReferentialJudgeResolver,
    _enforce_kind_invariants,
    _judge_max_turns,
    _judge_min_confidence,
)
from app.services.chat.referential_query_resolver import _prior_context_block
from app.services.chat.session_context_types import SessionMessageTurn
from app.services.chat.session_replay_policy import is_repeated_user_question
from app.services.chat.session_transcript import turns_to_resolver_transcript
from app.services.chat.structured_data_router import (
    StructuredDataRouterDecision,
    StructuredDataRouterResult,
    StatementFileCatalogEntry,
    _format_catalog_block,
    _sql_capabilities_block,
    build_statement_file_catalog,
    case_has_sql_statement_tables,
    finalize_structured_data_route,
)
from app.services.chat.turn_context_evidence import (
    PriorTurnEvidence,
    load_prior_turn_evidence_from_turns,
)
from app.services.chat.turn_context_resolution import (
    TurnContextResolution,
    _resolution_from_judge,
)

logger = logging.getLogger(__name__)

ExecutionTierHint = Literal[
    "no_retrieval",
    "clarify",
    "instant",
    "standard",
    "deep",
]


class TurnPrepPlannerDecision(BaseModel):
    """Single structured decision for one case-assistant turn before retrieval."""

    referential_kind: Literal[
        "none",
        "memory_synthesis",
        "scoped_deep_read",
        "citation_expand",
    ] = Field(
        description=(
            "none: new topic / full-case search. "
            "memory_synthesis: recap prior answer — no document search. "
            "scoped_deep_read: drill-down / deictic follow-up — scoped RAG. "
            "citation_expand: quote/source location — scoped RAG."
        ),
    )
    needs_document_retrieval: bool = Field(
        description="False only for memory_synthesis.",
    )
    standalone_query: str = Field(
        default="",
        description="Self-contained Russian query for search/SQL when follow-up or deictic.",
    )
    data_plane: Literal["rag", "sql", "hybrid", "skip"] = Field(
        default="rag",
        description=(
            "skip when memory_synthesis (no SQL/RAG). "
            "sql for statement tabular facts; rag for narrative; hybrid for both."
        ),
    )
    statement_file_ids: list[str] = Field(default_factory=list)
    rag_file_ids: list[str] = Field(default_factory=list)
    information_need: Literal[
        "tabular_aggregate",
        "tabular_list",
        "tabular_find",
        "document_narrative",
        "document_drill_down",
        "comparison",
        "unknown",
    ] = Field(default="unknown")
    execution_tier: ExecutionTierHint = Field(
        default="standard",
        description="Retrieval depth: instant/standard/deep; no_retrieval for chat-only.",
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    rationale: str = Field(default="", max_length=400)

    @field_validator("standalone_query", mode="before")
    @classmethod
    def _strip_standalone(cls, value: object) -> str:
        return str(value or "").strip()[:500]

    @field_validator("statement_file_ids", "rag_file_ids", mode="before")
    @classmethod
    def _normalize_file_ids(cls, value: object) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            value = [value]
        out: list[str] = []
        for item in value:  # type: ignore[union-attr]
            fid = str(item or "").strip()
            if fid and fid not in out:
                out.append(fid)
        return out


@dataclass(frozen=True)
class TurnPrepPlan:
    turn_context: TurnContextResolution
    structured_route: Optional[StructuredDataRouterResult]
    information_need: str
    execution_tier_hint: Optional[ExecutionTierHint]
    resolver: str
    confidence: float


def unified_turn_prep_planner_enabled() -> bool:
    return bool(getattr(config, "CASE_TURN_PREP_UNIFIED_PLANNER_ENABLED", True))


def _planner_max_tokens() -> int:
    return max(256, int(getattr(config, "CASE_TURN_PREP_UNIFIED_PLANNER_MAX_TOKENS", 640) or 640))


def _planner_model() -> str:
    return (
        getattr(config, "CASE_TURN_PREP_UNIFIED_PLANNER_MODEL", None)
        or getattr(config, "TURN_CONTEXT_LLM_JUDGE_MODEL", None)
        or getattr(config, "CASE_ASSISTANT_ROUTER_MODEL", "")
        or "yandexgpt-lite/latest"
    )


def _build_unified_prompt(
    *,
    question: str,
    turns: Sequence[SessionMessageTurn],
    prior_evidence: PriorTurnEvidence | None,
    dialog_history: str,
    conversation_summary: str,
    anchor_filenames: Sequence[str],
    catalog: Sequence[StatementFileCatalogEntry],
    sql_file_ids: Sequence[str],
    attached_file_ids: Optional[Sequence[str]],
    has_sql: bool,
) -> str:
    transcript = turns_to_resolver_transcript(list(turns), max_turns=_judge_max_turns())
    if not transcript.strip() and (dialog_history or "").strip():
        transcript = (dialog_history or "").strip()[:6000]

    prior_block = ""
    if prior_evidence is not None:
        prior_block = _prior_context_block(prior_evidence)

    summary = (conversation_summary or "").strip()
    files = ", ".join(str(x).strip() for x in anchor_filenames if str(x).strip())[:400]
    attached = ", ".join(attached_file_ids or []) or "[ничего не прикреплено]"

    repeat_hint = ""
    if turns and is_repeated_user_question(question, turns):
        repeat_hint = (
            "\nВАЖНО: пользователь повторяет тот же вопрос — referential_kind=none, "
            "needs_document_retrieval=true, data_plane по смыслу вопроса.\n"
        )

    sql_block = ""
    catalog_block = ""
    if has_sql:
        sql_block = f"\n{_sql_capabilities_block()}\n"
        catalog_block = (
            f"\nФайлы дела (каталог):\n{_format_catalog_block(catalog, sql_file_ids)}\n"
        )

    return (
        "Ты единый маршрутизатор юридического case-assistant. По транскрипту, каталогу файлов "
        "и новому вопросу верни ОДИН JSON-пакет для всего turn ДО поиска по документам.\n\n"
        "=== A. Память и follow-up (referential_kind) ===\n"
        "- memory_synthesis: пересказ/итог прошлого ответа без новых фактов из документов → "
        "needs_document_retrieval=false, data_plane=skip, execution_tier=no_retrieval.\n"
        "- scoped_deep_read: «подробнее», «детальнее», deictic («эта сумма», «п. 3») → "
        "needs_document_retrieval=true, standalone_query обязателен.\n"
        "- citation_expand: «где написано», «цитата», «откуда взял» → scoped RAG.\n"
        "- none: новая тема или полный поиск по делу.\n\n"
        "=== B. Источник данных (data_plane) ==="
        f"{sql_block}"
        "- rag: смысл/цитаты документов (возражение, иск, «о чём выписка», реквизиты в шапке).\n"
        "- sql: только табличные факты выписки (суммы, кол-во операций, период, поступления/списания).\n"
        "- hybrid: цифры из выписки И текст других документов.\n"
        "- skip: только для memory_synthesis.\n"
        "Не путай «поступления» (деньги на счёт) с «уступками» (право требования).\n"
        "«Сколько операций/поступлений за период» → sql + tabular_aggregate.\n\n"
        "information_need: tabular_* | document_narrative | document_drill_down | comparison.\n\n"
        "=== C. Файлы ===\n"
        "statement_file_ids — file_id выписки с SQL-таблицей (для sql/hybrid).\n"
        "rag_file_ids — file_id документов для RAG (для hybrid или узкий scope).\n"
        "Пустые списки = весь допустимый scope дела.\n\n"
        "=== D. Глубина поиска (execution_tier) ===\n"
        "instant — один факт; standard — один документ; deep — обзор/синтез; "
        "no_retrieval — memory_synthesis.\n\n"
        "standalone_query: самодостаточный русский запрос без «эта сумма» / «там».\n"
        f"{repeat_hint}"
        f"Сводка сессии:\n{summary or '[нет]'}\n\n"
        f"Файлы из прошлых цитат:\n{files or '[нет]'}\n"
        f"Прикреплённые file_id: {attached}\n"
        f"{catalog_block}\n"
        f"Транскрипт:\n{transcript or '[пусто]'}\n\n"
        f"Prior answer / evidence:\n{prior_block or '[нет prior assistant turn]'}\n\n"
        f"Новый вопрос пользователя:\n{question.strip()}\n"
    )


def _apply_planner_safety_invariants(
    decision: TurnPrepPlannerDecision,
    *,
    question: str,
    has_prior: bool,
) -> TurnPrepPlannerDecision:
    """Normalize LLM output before referential + routing merge."""
    need = str(decision.information_need or "unknown").strip().lower()
    plane = str(decision.data_plane or "rag").strip().lower()
    kind = str(decision.referential_kind or "none").strip().lower()
    updates: dict[str, object] = {}

    if need.startswith("tabular_") or plane in {"sql", "hybrid"}:
        updates.update(
            {
                "referential_kind": "none",
                "needs_document_retrieval": True,
                "data_plane": "sql" if plane in {"", "skip", "rag"} and plane != "hybrid" else plane,
                "execution_tier": "instant",
            }
        )
        if plane == "hybrid":
            updates["data_plane"] = "hybrid"
    elif need in {"document_narrative", "document_drill_down", "comparison"}:
        if kind == "memory_synthesis" or plane == "skip":
            updates.update(
                {
                    "referential_kind": "scoped_deep_read" if has_prior else "none",
                    "needs_document_retrieval": True,
                    "data_plane": "rag",
                    "execution_tier": "standard",
                }
            )
    elif kind in {"scoped_deep_read", "citation_expand", "none"} and plane != "skip":
        updates["needs_document_retrieval"] = True
        if str(decision.execution_tier or "") == "no_retrieval":
            updates["execution_tier"] = "standard"

    # Short SQL period follow-up («а в мае 2026») must not become chat-only memory.
    if has_prior and kind == "memory_synthesis":
        from app.services.chat.referential_classifier import needs_prior_turn_resolution

        if needs_prior_turn_resolution(question) and not str(
            decision.rationale or ""
        ).lower().startswith("recap"):
            updates.update(
                {
                    "referential_kind": "none",
                    "needs_document_retrieval": True,
                    "execution_tier": "instant",
                }
            )

    if not updates:
        return decision
    return decision.model_copy(update=updates)


def _judge_result_from_planner(
    *,
    question: str,
    has_prior: bool,
    decision: TurnPrepPlannerDecision,
) -> ReferentialJudgeResult:
    regex_kind = classify_referential_kind(question, has_prior=has_prior)
    regex_result = ReferentialJudgeResult(
        referential_kind=regex_kind,
        needs_document_retrieval=regex_kind not in {"memory_synthesis"},
        confidence=0.92 if regex_kind != "none" else 0.55,
        reason=f"regex_{regex_kind}",
        resolver="regex_fallback",
    )

    if not has_prior:
        return regex_result

    llm_kind_raw = str(decision.referential_kind or "none").strip().lower()
    llm_kind: ReferentialKind = (
        llm_kind_raw
        if llm_kind_raw in {"none", "memory_synthesis", "scoped_deep_read", "citation_expand"}
        else "none"
    )
    llm_kind, llm_needs_docs = _enforce_kind_invariants(
        llm_kind,
        bool(decision.needs_document_retrieval),
    )
    llm_conf = max(0.0, min(1.0, float(decision.confidence or 0.0)))
    llm_reason = (decision.rationale or "unified_planner")[:320]
    standalone = re.sub(r"\s+", " ", (decision.standalone_query or "").strip())
    min_conf = _judge_min_confidence()

    if (
        llm_kind == "memory_synthesis"
        and regex_result.referential_kind in {"scoped_deep_read", "citation_expand"}
    ):
        return ReferentialJudgeResult(
            referential_kind=regex_result.referential_kind,
            needs_document_retrieval=True,
            confidence=max(regex_result.confidence, llm_conf),
            reason=f"regex_drill_down_overrides_memory;{llm_reason[:200]}",
            resolver="regex_safety",
            standalone_query=standalone or regex_result.standalone_query,
        )

    if llm_conf >= min_conf:
        resolver: ReferentialJudgeResolver = "llm"
        if regex_result.referential_kind == llm_kind and regex_result.referential_kind != "none":
            resolver = "llm_regex_agree"
        return ReferentialJudgeResult(
            referential_kind=llm_kind,
            needs_document_retrieval=llm_needs_docs,
            confidence=llm_conf,
            reason=llm_reason,
            resolver=resolver,
            standalone_query=standalone,
        )

    if regex_result.referential_kind == "memory_synthesis" and llm_kind != "memory_synthesis":
        return ReferentialJudgeResult(
            referential_kind="memory_synthesis",
            needs_document_retrieval=False,
            confidence=max(regex_result.confidence, llm_conf),
            reason=f"regex_safety;{llm_reason[:200]}",
            resolver="regex_safety",
        )

    if regex_result.referential_kind != "none":
        return ReferentialJudgeResult(
            referential_kind=regex_result.referential_kind,
            needs_document_retrieval=regex_result.needs_document_retrieval,
            confidence=regex_result.confidence,
            reason=f"regex_fallback;{llm_reason[:160]}",
            resolver="regex_fallback",
            standalone_query=standalone,
        )

    return ReferentialJudgeResult(
        referential_kind=llm_kind,
        needs_document_retrieval=llm_needs_docs,
        confidence=llm_conf,
        reason=f"planner_low_conf;{llm_reason[:160]}",
        resolver="llm",
        standalone_query=standalone,
    )


def _structured_route_from_planner(
    *,
    case_id: str,
    decision: TurnPrepPlannerDecision,
    catalog: Sequence[StatementFileCatalogEntry],
    sql_file_ids: Sequence[str],
    attached_file_ids: Optional[Sequence[str]],
    judge: ReferentialJudgeResult,
) -> Optional[StructuredDataRouterResult]:
    plane = str(decision.data_plane or "rag").strip().lower()
    if judge.referential_kind == "memory_synthesis" or plane == "skip":
        return None

    if not sql_file_ids:
        need = str(decision.information_need or "unknown")
        rag_ids = list(decision.rag_file_ids or [])
        return StructuredDataRouterResult(
            data_plane="rag",
            statement_file_ids=[],
            rag_file_ids=rag_ids,
            confidence=float(decision.confidence or 0.8),
            reason=(decision.rationale or "unified_planner_rag")[:400],
            resolver="unified_planner",
            information_need=need,
        )

    router_decision = StructuredDataRouterDecision(
        data_plane=(
            "rag"
            if str(decision.data_plane or "rag").lower() == "skip"
            else decision.data_plane  # type: ignore[arg-type]
        ),
        statement_file_ids=list(decision.statement_file_ids or []),
        rag_file_ids=list(decision.rag_file_ids or []),
        confidence=float(decision.confidence or 0.8),
        rationale=(decision.rationale or "")[:400],
        information_need=decision.information_need,
    )
    return finalize_structured_data_route(
        case_id=case_id,
        decision=router_decision,
        catalog=catalog,
        sql_file_ids=sql_file_ids,
        attached_file_ids=attached_file_ids,
        information_need=str(decision.information_need or "unknown"),
        resolver_hint="unified_planner",
    )


def _invoke_unified_planner(prompt: str, *, question_chars: int) -> TurnPrepPlannerDecision | None:
    if not unified_turn_prep_planner_enabled():
        return None
    try:
        from app.services.llm_factory import create_llm
        from app.services.observability.assistant_pipeline_langfuse_tracing import assistant_step_span
        from app.services.observability.langfuse_service import get_langchain_callbacks

        llm = create_llm(
            model=_planner_model(),
            temperature=0.0,
            max_tokens=_planner_max_tokens(),
            use_rate_limiting=False,
            cache_enabled=False,
        )
        structured = llm.with_structured_output(TurnPrepPlannerDecision)
        callbacks = get_langchain_callbacks(tags=["assistant", "turn_prep_planner"])

        with assistant_step_span(
            "case",
            "http.unified_turn_prep_planner",
            input_payload={"question_chars": question_chars},
        ) as span_out:
            result: TurnPrepPlannerDecision = structured.invoke(
                [
                    SystemMessage(
                        content=(
                            "Ты детерминированный маршрутизатор юридического ассистента. "
                            "Верни один JSON: память/follow-up, data_plane, file_ids, "
                            "information_need, execution_tier. "
                            "memory_synthesis → needs_document_retrieval=false, data_plane=skip. "
                            "«Подробнее/детальнее» → scoped_deep_read, не memory_synthesis."
                        )
                    ),
                    HumanMessage(content=prompt),
                ],
                config={"callbacks": callbacks} if callbacks else None,
            )
            span_out["referential_kind"] = result.referential_kind
            span_out["data_plane"] = result.data_plane
            span_out["information_need"] = result.information_need
            span_out["confidence"] = float(result.confidence or 0.0)
        return result
    except Exception as exc:
        logger.warning("[TurnPrepPlanner] LLM invoke failed: %s", exc)
        return None


def plan_case_turn_prep(
    db: Session,
    *,
    case_id: str,
    question: str,
    turns: Sequence[SessionMessageTurn],
    dialog_history: str = "",
    conversation_summary: str = "",
    anchor_filenames: Sequence[str] = (),
    attached_file_ids: Optional[Sequence[str]] = None,
) -> TurnPrepPlan | None:
    """
    Single LLM call for turn context + structured data routing.

    Returns None when planner disabled or LLM failed (caller should use legacy path).
    """
    q = (question or "").strip()
    if not q or not unified_turn_prep_planner_enabled():
        return None

    prior_evidence = load_prior_turn_evidence_from_turns(turns)
    has_prior = prior_evidence is not None and bool(
        (prior_evidence.assistant_excerpt or "").strip()
    )

    has_sql = case_has_sql_statement_tables(db, str(case_id))
    sql_file_ids: list[str] = []
    catalog: list[StatementFileCatalogEntry] = []
    if has_sql:
        from app.services.case_file_transaction_service import CaseFileTransactionService

        sql_file_ids = list(CaseFileTransactionService.list_transaction_file_ids(db, case_id))
        catalog = build_statement_file_catalog(
            db,
            case_id=case_id,
            attached_file_ids=attached_file_ids,
        )

    prompt = _build_unified_prompt(
        question=q,
        turns=turns,
        prior_evidence=prior_evidence,
        dialog_history=dialog_history,
        conversation_summary=conversation_summary,
        anchor_filenames=anchor_filenames,
        catalog=catalog,
        sql_file_ids=sql_file_ids,
        attached_file_ids=attached_file_ids,
        has_sql=has_sql,
    )
    decision = _invoke_unified_planner(prompt, question_chars=len(q))
    if decision is None:
        return None

    decision = _apply_planner_safety_invariants(
        decision,
        question=q,
        has_prior=has_prior,
    )

    judge = _judge_result_from_planner(question=q, has_prior=has_prior, decision=decision)
    turn_context = _resolution_from_judge(
        original=q,
        judge=judge,
        prior_evidence=prior_evidence,
        dialog_history=dialog_history,
        conversation_summary=conversation_summary,
        anchor_filenames=anchor_filenames,
    )

    if list(decision.rag_file_ids or []) and judge.referential_kind != "memory_synthesis":
        extra = [fid for fid in decision.rag_file_ids if fid not in turn_context.inherited_file_ids]
        if extra:
            turn_context = TurnContextResolution(
                original_question=turn_context.original_question,
                standalone_query=turn_context.standalone_query,
                referential_kind=turn_context.referential_kind,
                inherited_file_ids=tuple(list(turn_context.inherited_file_ids) + extra),
                anchor_chunk_ids=turn_context.anchor_chunk_ids,
                suggested_intent=turn_context.suggested_intent,
                needs_document_retrieval=turn_context.needs_document_retrieval,
                prefer_parent_context=turn_context.prefer_parent_context,
                reason=f"{turn_context.reason};planner_file_scope",
                confidence=turn_context.confidence,
                query_resolver=turn_context.query_resolver,
                routing_resolver="unified_planner",
            )

    structured_route = _structured_route_from_planner(
        case_id=str(case_id),
        decision=decision,
        catalog=catalog,
        sql_file_ids=sql_file_ids,
        attached_file_ids=attached_file_ids,
        judge=judge,
    )

    tier_hint: Optional[ExecutionTierHint] = decision.execution_tier
    if judge.referential_kind == "memory_synthesis":
        tier_hint = "no_retrieval"

    need = str(decision.information_need or "unknown")
    if structured_route is not None and structured_route.information_need not in {"", "unknown"}:
        need = structured_route.information_need

    return TurnPrepPlan(
        turn_context=turn_context,
        structured_route=structured_route,
        information_need=need,
        execution_tier_hint=tier_hint,
        resolver="unified_planner",
        confidence=float(decision.confidence or 0.0),
    )
