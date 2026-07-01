"""
LLM router: when to use SQL over bank-statement rows vs normal document RAG.

Runs before case_transaction_agent. Uses the same primary LLM as legal answers
(create_legal_llm → YANDEX_GPT_MODEL_URI / Qwen).
data (operations, amounts, counts, periods). Narrative questions about any document
—including «о чём выписка»—route to RAG.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.config import config
from app.models.analysis import DocumentClassification
from app.models.case import File as CaseFile
from app.services.case_file_transaction_service import (
    CaseFileTransactionService,
    feature_enabled as transactions_feature_enabled,
)

logger = logging.getLogger(__name__)

StructuredDataPlane = Literal["rag", "sql", "hybrid"]
StructuredDataResolver = Literal[
    "precondition_skip",
    "http_prep",
    "unified_planner",
    "scope_gate_rag_only",
    "llm",
    "llm_low_confidence",
    "llm_invalid_scope",
    "llm_invalid_hybrid_scope",
    "llm_failed",
]


@dataclass(frozen=True)
class StatementFileCatalogEntry:
    file_id: str
    filename: str
    doc_type: str
    has_sql_table: bool


@dataclass(frozen=True)
class StructuredDataRouterResult:
    data_plane: StructuredDataPlane
    statement_file_ids: List[str]
    rag_file_ids: List[str]
    confidence: float
    reason: str
    resolver: StructuredDataResolver
    information_need: str = "unknown"


class StructuredDataRouterDecision(BaseModel):
    """Routing decision for one user turn."""

    data_plane: Literal["rag", "sql", "hybrid"] = Field(
        description=(
            "rag: смысл документов, цитаты, доводы (возражения, договоры, «о чём выписка»). "
            "sql: только табличные факты выписки (суммы, кол-во, период, операция по дате). "
            "hybrid: нужны И цифры из выписки, И текст других документов (сравнение, сверка)."
        ),
    )
    statement_file_ids: List[str] = Field(
        default_factory=list,
        description=(
            "file_id с SQL-таблицей для sql/hybrid. Пусто = все выписки в scope."
        ),
    )
    rag_file_ids: List[str] = Field(
        default_factory=list,
        description=(
            "file_id для текстового RAG при hybrid (возражение, иск и т.д.). "
            "Пусто = все не-SQL файлы дела."
        ),
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    rationale: str = Field(default="", max_length=400)
    information_need: Literal[
        "tabular_aggregate",
        "tabular_list",
        "tabular_find",
        "document_narrative",
        "document_drill_down",
        "comparison",
        "unknown",
    ] = Field(
        default="unknown",
        description=(
            "Тип информации: tabular_* для цифр выписки; document_narrative для смысла документа; "
            "document_drill_down для углубления; comparison для сверки."
        ),
    )

    @field_validator("statement_file_ids", "rag_file_ids", mode="before")
    @classmethod
    def _normalize_file_ids(cls, value: object) -> List[str]:
        if not value:
            return []
        if isinstance(value, str):
            value = [value]
        out: List[str] = []
        for item in value:  # type: ignore[union-attr]
            fid = str(item or "").strip()
            if fid and fid not in out:
                out.append(fid)
        return out


def structured_data_router_enabled() -> bool:
    return bool(getattr(config, "STRUCTURED_DATA_LLM_ROUTER_ENABLED", True))


def _router_min_confidence() -> float:
    return max(
        0.0,
        min(1.0, float(getattr(config, "STRUCTURED_DATA_LLM_ROUTER_MIN_CONF", 0.65) or 0.65)),
    )


def _router_max_catalog_files() -> int:
    return max(1, int(getattr(config, "STRUCTURED_DATA_LLM_ROUTER_MAX_FILES", 40) or 40))


def _batch_doc_types(db: Session, file_ids: Sequence[str]) -> Dict[str, str]:
    if not file_ids:
        return {}
    out: Dict[str, str] = {}
    try:
        rows = (
            db.query(DocumentClassification.file_id, DocumentClassification.doc_type)
            .filter(DocumentClassification.file_id.in_(list(file_ids)))
            .all()
        )
        for fid, dtype in rows:
            if fid and dtype and str(fid) not in out:
                out[str(fid)] = str(dtype)
    except Exception:
        logger.debug("structured_data_router doc_type batch failed", exc_info=True)
    return out


def build_statement_file_catalog(
    db: Session,
    *,
    case_id: str,
    attached_file_ids: Optional[Sequence[str]] = None,
) -> List[StatementFileCatalogEntry]:
    """All case files with flag whether SQL transaction table is available."""
    if not db or not case_id:
        return []

    q = db.query(CaseFile.id, CaseFile.filename).filter(CaseFile.case_id == case_id)
    if attached_file_ids:
        ids = [str(fid).strip() for fid in attached_file_ids if str(fid).strip()]
        if ids:
            q = q.filter(CaseFile.id.in_(ids))
    rows = q.limit(_router_max_catalog_files()).all()
    if not rows:
        return []

    file_ids = [str(r[0]) for r in rows if r[0]]
    doc_types = _batch_doc_types(db, file_ids)
    sql_ids = set(CaseFileTransactionService.list_transaction_file_ids(db, case_id))

    catalog: List[StatementFileCatalogEntry] = []
    for fid, filename in rows:
        if not fid:
            continue
        catalog.append(
            StatementFileCatalogEntry(
                file_id=str(fid),
                filename=str(filename or fid),
                doc_type=doc_types.get(str(fid), "other"),
                has_sql_table=str(fid) in sql_ids,
            )
        )
    return catalog


def _format_catalog_block(
    catalog: Sequence[StatementFileCatalogEntry],
    sql_file_ids: Sequence[str],
) -> str:
    if not catalog:
        return "[нет файлов в каталоге]"
    lines: List[str] = []
    sql_set = set(sql_file_ids)
    for entry in catalog:
        sql_flag = "да" if entry.file_id in sql_set else "нет"
        lines.append(
            f"- id={entry.file_id} | {entry.filename} | тип={entry.doc_type} | SQL-таблица={sql_flag}"
        )
    return "\n".join(lines)


def _sql_capabilities_block() -> str:
    return (
        "SQL-таблица выписки умеет: дата/время операции, сумма (со знаком), описание, контрагент, "
        "фильтр по периоду, count/sum/list/find по строкам, поступления (credit) и списания (debit)."
    )


def _build_router_prompt(
    *,
    question: str,
    catalog: Sequence[StatementFileCatalogEntry],
    sql_file_ids: Sequence[str],
    attached_file_ids: Optional[Sequence[str]],
    dialog_history: Optional[str] = None,
    information_need: str = "unknown",
) -> str:
    attached = ", ".join(attached_file_ids or []) or "[ничего не прикреплено]"
    history_block = ""
    if dialog_history and dialog_history.strip():
        history_block = (
            f"\nНедавний диалог (для follow-up):\n{dialog_history.strip()[:2500]}\n"
        )
    need_block = ""
    need = (information_need or "unknown").strip().lower()
    if need != "unknown":
        need_block = f"\nInformation need (from turn contract): {need}\n"
    return (
        "Классифицируй вопрос юриста по делу о банкротстве.\n\n"
        f"{_sql_capabilities_block()}\n\n"
        "data_plane=sql — ответ только из таблицы операций выписки.\n"
        "data_plane=rag — смысл/цитаты из текста документов (возражение, иск, договор, "
        "«о чём выписка», владелец счёта, реквизиты в шапке выписки).\n"
        "data_plane=hybrid — нужны цифры из выписки И содержание других документов "
        "(сверка, сравнение, «есть ли в выписке то, о чём пишут в возражении»).\n\n"
        "information_need обязателен:\n"
        "- tabular_aggregate / tabular_list / tabular_find — цифры и строки операций;\n"
        "- document_narrative — смысл документа, шапка, субъект, «кто/о чём/чей счёт»;\n"
        "- document_drill_down — углубление в уже обсуждённый документ.\n\n"
        "Примеры:\n"
        "- «О чём возражение ШАК» → rag, document_narrative\n"
        "- «О чём эта выписка» → rag, document_narrative\n"
        "- «Кто владелец счёта в выписке» → rag, document_narrative\n"
        "- «Сколько списаний за май 2024» → sql, tabular_aggregate\n"
        "- «Сколько поступлений за май 2026» → sql, tabular_aggregate\n"
        "- «Сумма поступлений за май» → sql, tabular_aggregate\n"
        "- «Операция 11.06.2026 в 19:28» → sql, tabular_find\n"
        "- «Есть ли платежи Иванову в выписке» → sql, tabular_list\n"
        "- «Совпадают ли платежи в выписке с доводами возражения» → hybrid, comparison\n\n"
        f"Прикреплённые file_id: {attached}\n"
        f"{history_block}"
        f"{need_block}"
        f"Файлы дела (каталог):\n{_format_catalog_block(catalog, sql_file_ids)}\n\n"
        f"Вопрос пользователя:\n{question.strip()}\n"
    )


def _resolve_sql_scope(
    *,
    decision: StructuredDataRouterDecision,
    sql_file_ids: Sequence[str],
    attached_file_ids: Optional[Sequence[str]],
) -> List[str]:
    allowed = set(sql_file_ids)
    if not allowed:
        return []

    chosen = [fid for fid in (decision.statement_file_ids or []) if fid in allowed]
    if chosen:
        return chosen

    if attached_file_ids:
        attached_sql = [fid for fid in attached_file_ids if fid in allowed]
        if attached_sql:
            return attached_sql

    return list(allowed)


def _resolve_rag_scope(
    *,
    decision: StructuredDataRouterDecision,
    catalog: Sequence[StatementFileCatalogEntry],
    sql_file_ids: Sequence[str],
    attached_file_ids: Optional[Sequence[str]],
) -> List[str]:
    sql_set = set(sql_file_ids)
    catalog_ids = [e.file_id for e in catalog]
    allowed_non_sql = [fid for fid in catalog_ids if fid not in sql_set]

    chosen = [
        fid
        for fid in (decision.rag_file_ids or [])
        if fid in allowed_non_sql or fid not in sql_set
    ]
    if chosen:
        return chosen

    if attached_file_ids:
        attached_rag = [fid for fid in attached_file_ids if fid not in sql_set]
        if attached_rag:
            return attached_rag

    return allowed_non_sql


def _invoke_llm_router(prompt: str, *, question_chars: int) -> StructuredDataRouterDecision | None:
    if not structured_data_router_enabled():
        return None

    try:
        from app.services.llm_factory import create_llm
        from app.services.observability.assistant_pipeline_langfuse_tracing import assistant_step_span
        from app.services.observability.langfuse_service import get_langchain_callbacks

        max_tokens = int(getattr(config, "STRUCTURED_DATA_LLM_ROUTER_MAX_TOKENS", 512) or 512)
        router_model = (
            getattr(config, "CASE_ASSISTANT_ROUTER_MODEL", None) or "yandexgpt-lite/latest"
        )
        llm = create_llm(
            model=router_model,
            temperature=0.0,
            max_tokens=max_tokens,
            use_rate_limiting=False,
            cache_enabled=False,
        )
        structured = llm.with_structured_output(StructuredDataRouterDecision)
        callbacks = get_langchain_callbacks(tags=["assistant", "structured_data_router"])

        with assistant_step_span(
            "case",
            "structured_data_router",
            input_payload={"question_chars": question_chars},
        ) as span_out:
            decision: StructuredDataRouterDecision = structured.invoke(
                [
                    SystemMessage(
                        content=(
                            "Ты детерминированный маршрутизатор юридического ассистента. "
                            "sql — табличные факты выписки (операции, суммы, поступления, списания, периоды); "
                            "rag — смысл и цитаты из текста документов; hybrid — оба источника. "
                            "Не путай «поступления» (деньги на счёт) с «уступками» (право требования). "
                            "Вопросы «сколько поступлений/списаний/операций» — всегда sql + tabular_aggregate."
                        )
                    ),
                    HumanMessage(content=prompt),
                ],
                config={"callbacks": callbacks} if callbacks else None,
            )
            span_out["data_plane"] = decision.data_plane
            span_out["confidence"] = float(decision.confidence or 0.0)
            span_out["statement_file_ids"] = list(decision.statement_file_ids or [])
            span_out["rag_file_ids"] = list(decision.rag_file_ids or [])
        return decision
    except Exception as exc:
        logger.warning("[StructuredDataRouter] LLM invoke failed: %s", exc)
        return None


def _precondition_skip_result(reason: str) -> StructuredDataRouterResult:
    return StructuredDataRouterResult(
        data_plane="rag",
        statement_file_ids=[],
        rag_file_ids=[],
        confidence=1.0,
        reason=reason,
        resolver="precondition_skip",
        information_need="unknown",
    )


def _merge_information_need(
    contract_need: str,
    decision: StructuredDataRouterDecision | None,
) -> str:
    router_need = str(decision.information_need or "unknown").strip().lower() if decision else "unknown"
    cn = (contract_need or "unknown").strip().lower()
    if cn not in {"unknown", ""}:
        return cn
    if router_need not in {"unknown", ""}:
        return router_need
    return "unknown"


def case_has_sql_statement_tables(db: Session, case_id: str) -> bool:
    """Fast gate: skip LLM router when case has no ingested statement rows."""
    if not db or not case_id:
        return False
    if not transactions_feature_enabled():
        return False
    return bool(CaseFileTransactionService.list_transaction_file_ids(db, case_id))


def finalize_structured_data_route(
    *,
    case_id: str,
    decision: StructuredDataRouterDecision,
    catalog: Sequence[StatementFileCatalogEntry],
    sql_file_ids: Sequence[str],
    attached_file_ids: Optional[Sequence[str]] = None,
    information_need: str = "unknown",
    resolver_hint: Optional[StructuredDataResolver] = None,
) -> StructuredDataRouterResult:
    """Apply LLM routing decision with scope validation and capability invariants."""
    effective_need = _merge_information_need(information_need, decision)
    plane_raw = str(decision.data_plane or "rag").strip().lower()
    if plane_raw == "sql":
        plane: StructuredDataPlane = "sql"
    elif plane_raw == "hybrid":
        plane = "hybrid"
    else:
        plane = "rag"
    conf = max(0.0, min(1.0, float(decision.confidence or 0.0)))
    rationale = (decision.rationale or "").strip()[:400]
    resolved_via = resolver_hint or "llm"

    from app.services.chat.structured_data_capability import enforce_data_plane_capability

    cap_plane, cap_reason = enforce_data_plane_capability(
        plane,
        effective_need,  # type: ignore[arg-type]
        has_sql_tables=bool(sql_file_ids),
    )
    if cap_plane != plane:
        plane = cap_plane  # type: ignore[assignment]
        if cap_reason:
            rationale = f"{rationale};{cap_reason}".strip(";")[:400]
        if cap_plane == "rag":
            resolved_via = "capability_invariant"

    if plane in {"sql", "hybrid"} and conf < _router_min_confidence():
        logger.info(
            "[StructuredDataRouter] case=%s plane=rag resolver=llm_low_confidence conf=%.2f",
            case_id,
            conf,
        )
        return StructuredDataRouterResult(
            data_plane="rag",
            statement_file_ids=[],
            rag_file_ids=[],
            confidence=conf,
            reason=rationale or "low_confidence",
            resolver="llm_low_confidence",
            information_need=effective_need,
        )

    if plane == "rag":
        logger.info(
            "[StructuredDataRouter] case=%s plane=rag resolver=%s conf=%.2f reason=%s",
            case_id,
            resolved_via,
            conf,
            (rationale or "narrative")[:120],
        )
        return StructuredDataRouterResult(
            data_plane="rag",
            statement_file_ids=[],
            rag_file_ids=[],
            confidence=conf,
            reason=rationale or "narrative",
            resolver=resolved_via,
            information_need=effective_need,
        )

    sql_scope = _resolve_sql_scope(
        decision=decision,
        sql_file_ids=sql_file_ids,
        attached_file_ids=attached_file_ids,
    )
    if not sql_scope:
        logger.info(
            "[StructuredDataRouter] case=%s plane=rag resolver=llm_invalid_scope",
            case_id,
        )
        return StructuredDataRouterResult(
            data_plane="rag",
            statement_file_ids=[],
            rag_file_ids=[],
            confidence=conf,
            reason=rationale or "invalid_sql_scope",
            resolver="llm_invalid_scope",
            information_need=effective_need,
        )

    if plane == "hybrid":
        rag_scope = _resolve_rag_scope(
            decision=decision,
            catalog=catalog,
            sql_file_ids=sql_file_ids,
            attached_file_ids=attached_file_ids,
        )
        if not rag_scope:
            logger.info(
                "[StructuredDataRouter] case=%s plane=sql resolver=hybrid_no_rag_docs",
                case_id,
            )
            plane = "sql"
        else:
            logger.info(
                "[StructuredDataRouter] case=%s plane=hybrid sql_files=%s rag_files=%s conf=%.2f",
                case_id,
                len(sql_scope),
                len(rag_scope),
                conf,
            )
            return StructuredDataRouterResult(
                data_plane="hybrid",
                statement_file_ids=sql_scope,
                rag_file_ids=rag_scope,
                confidence=conf,
                reason=rationale or "hybrid_query",
                resolver=resolved_via,
                information_need=effective_need,
            )

    logger.info(
        "[StructuredDataRouter] case=%s plane=sql files=%s conf=%.2f reason=%s",
        case_id,
        len(sql_scope),
        conf,
        (rationale or "structured_query")[:120],
    )
    return StructuredDataRouterResult(
        data_plane="sql",
        statement_file_ids=sql_scope,
        rag_file_ids=[],
        confidence=conf,
        reason=rationale or "structured_query",
        resolver=resolved_via,
        information_need=effective_need,
    )


def route_structured_data_plane(
    db: Session,
    *,
    case_id: str,
    question: str,
    attached_file_ids: Optional[Sequence[str]] = None,
    dialog_history: Optional[str] = None,
    resolver_hint: Optional[StructuredDataResolver] = None,
    information_need: str = "unknown",
    eligible_sql_file_ids: Optional[Sequence[str]] = None,
    scope_rag_file_ids: Optional[Sequence[str]] = None,
) -> StructuredDataRouterResult:
    """
    Decide whether this turn should use SQL transaction tools or document RAG.

    Safe default on any failure: rag (skip SQL agent).

    When eligible_sql_file_ids is set (scope gate), only those files are SQL candidates.
    """
    q = (question or "").strip()
    if not q:
        return _precondition_skip_result("empty_question")

    agent_on = transactions_feature_enabled() and bool(
        getattr(config, "CASE_TRANSACTION_AGENT_ENABLED", True)
    )
    if not agent_on or not db or not case_id:
        return _precondition_skip_result("agent_disabled")

    sql_file_ids = CaseFileTransactionService.list_transaction_file_ids(db, case_id)
    if eligible_sql_file_ids is not None:
        allowed = set(sql_file_ids)
        sql_file_ids = [fid for fid in eligible_sql_file_ids if fid in allowed]
    if not sql_file_ids:
        return _precondition_skip_result("no_sql_files_in_case")

    catalog = build_statement_file_catalog(
        db,
        case_id=case_id,
        attached_file_ids=attached_file_ids,
    )
    if scope_rag_file_ids:
        rag_scope = {str(x).strip() for x in scope_rag_file_ids if str(x).strip()}
        if rag_scope:
            catalog = [e for e in catalog if e.file_id in rag_scope or e.file_id in set(sql_file_ids)]
    prompt = _build_router_prompt(
        question=q,
        catalog=catalog,
        sql_file_ids=sql_file_ids,
        attached_file_ids=attached_file_ids,
        dialog_history=dialog_history,
        information_need=information_need,
    )
    decision = _invoke_llm_router(prompt, question_chars=len(q))
    if decision is None:
        effective_need = _merge_information_need(information_need, None)
        logger.info(
            "[StructuredDataRouter] case=%s plane=rag resolver=llm_failed",
            case_id,
        )
        return StructuredDataRouterResult(
            data_plane="rag",
            statement_file_ids=[],
            rag_file_ids=[],
            confidence=0.0,
            reason="llm_failed",
            resolver="llm_failed",
            information_need=effective_need,
        )

    return finalize_structured_data_route(
        case_id=case_id,
        decision=decision,
        catalog=catalog,
        sql_file_ids=sql_file_ids,
        attached_file_ids=attached_file_ids,
        information_need=information_need,
        resolver_hint=resolver_hint,
    )
