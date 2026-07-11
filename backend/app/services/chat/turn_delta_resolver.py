"""
Resolve structured delta for referential follow-ups using prior turn state.

Uses LLM structured output when enabled; deterministic inheritance for
statement analytics scope (period, file, operation) without phrase lists.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.services.chat.conversation_turn_state import (
    ConversationTurnState,
    InformationNeed,
    merge_sql_plan_hints,
)
from app.services.chat.tabular_metric_slot import resolve_sql_metric_dimension
from app.services.chat.referential_classifier import (
    ReferentialKind,
    needs_prior_turn_resolution,
)
from app.services.chat.statement_sql_plan_normalize import (
    clears_statement_period,
    _format_dmy,
    infer_period_from_question,
)
from app.services.chat.turn_context_evidence import PriorTurnEvidence

logger = logging.getLogger(__name__)

_AGGREGATE_OPS = frozenset({"count", "sum", "group"})
_LIST_OPS = frozenset({"list", "find", "top"})
_DETAIL_RE = re.compile(
    r"\b(?:подробн|детальн|перечисл|какие|какая|какой|покажи|пришли|выведи)\w*",
    re.IGNORECASE,
)
_TOTAL_RE = re.compile(r"\b(?:общ\w+\s+сумм|итог\w*|сумма\s+всех)\b", re.IGNORECASE)


class TurnDeltaDecision(BaseModel):
    self_contained_query: str = Field(
        description="One self-contained Russian query for search or SQL planning.",
    )
    information_need: Literal[
        "tabular_aggregate",
        "tabular_list",
        "tabular_find",
        "document_narrative",
        "document_drill_down",
        "comparison",
        "unknown",
    ] = "unknown"
    operation: Optional[Literal["count", "sum", "list", "find", "top", "group"]] = Field(
        default=None,
        description="SQL operation when need is tabular; null to inherit prior.",
    )
    inherit_period: bool = True
    inherit_file: bool = True
    confidence: float = Field(ge=0.0, le=1.0, default=0.75)
    rationale: str = Field(default="", max_length=300)

    @field_validator("self_contained_query", mode="before")
    @classmethod
    def _strip_query(cls, value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())


@dataclass(frozen=True)
class TurnDeltaResult:
    effective_query: str
    information_need: InformationNeed
    sql_plan_hints: Dict[str, str]
    resolver: str
    reason: str


def turn_delta_llm_enabled() -> bool:
    from app.config import config

    return bool(getattr(config, "TURN_DELTA_LLM_ENABLED", True))


def _is_statement_period_follow_up(
    question: str,
    prior: ConversationTurnState,
) -> bool:
    """«а в июне», «за май 2026» after statement analytics — SQL period shift."""
    if prior.domain != "statement_analytics":
        return False
    return infer_period_from_question(question).kind != "unspecified"


def _period_hints_from_question(question: str) -> Dict[str, str]:
    hint = infer_period_from_question(question)
    if hint.kind == "single_day" and hint.on_date is not None:
        return {
            "on_date": _format_dmy(hint.on_date),
            "date_from": "",
            "date_to": "",
        }
    if (
        hint.kind in {"date_range", "calendar_month"}
        and hint.date_from is not None
        and hint.date_to is not None
    ):
        return {
            "on_date": "",
            "date_from": _format_dmy(hint.date_from),
            "date_to": _format_dmy(hint.date_to),
        }
    return {}


def _detail_requested(question: str) -> bool:
    return bool(_DETAIL_RE.search((question or "").strip()))


def _operation_override_for_follow_up(
    *,
    question: str,
    prior: ConversationTurnState,
    metric: str,
) -> str:
    q = (question or "").strip()
    if not q:
        return ""

    if _detail_requested(q):
        return "list"

    if prior.operation in _LIST_OPS and metric == "sum" and not _TOTAL_RE.search(q):
        return "list"
    if prior.operation in _LIST_OPS and metric == "count":
        return "list"
    if metric == "sum":
        return "sum"
    if metric == "count":
        return "count"
    return ""


def _is_referential_follow_up(
    question: str,
    *,
    referential_kind: ReferentialKind,
    has_prior_state: bool,
    prior_turn_state: Optional[ConversationTurnState] = None,
) -> bool:
    q = (question or "").strip()
    if not q or not has_prior_state:
        return False
    if referential_kind in {"scoped_deep_read", "citation_expand"}:
        return True
    if referential_kind == "memory_synthesis":
        return False
    if prior_turn_state is not None and _is_statement_period_follow_up(question, prior_turn_state):
        return True
    return needs_prior_turn_resolution(q)


def _deterministic_delta(
    *,
    question: str,
    prior: ConversationTurnState,
    referential_kind: ReferentialKind,
    prior_excerpt: str,
) -> TurnDeltaResult:
    q = (question or "").strip()
    need: InformationNeed = "unknown"
    op_override = ""
    metric = resolve_sql_metric_dimension(q)

    if prior.domain == "statement_analytics":
        need = "tabular_aggregate"
        if prior.operation in _LIST_OPS:
            need = "tabular_list"
        op_override = _operation_override_for_follow_up(
            question=q,
            prior=prior,
            metric=metric,
        )
        if op_override in _LIST_OPS:
            need = "tabular_list"
        elif op_override in _AGGREGATE_OPS:
            need = "tabular_aggregate"

    if prior.domain == "document_rag":
        if referential_kind in {"scoped_deep_read", "citation_expand"}:
            need = "document_drill_down"
        else:
            need = "document_narrative"

    hints = merge_sql_plan_hints(
        prior,
        operation_override=op_override,
        inherit_period=not bool(_period_hints_from_question(q)) and not clears_statement_period(q),
        inherit_file=True,
    )
    hints.update(_period_hints_from_question(q))
    if op_override:
        hints["operation"] = op_override

    context = prior.context_line()
    excerpt = (prior_excerpt or "").strip()
    if context and excerpt:
        effective = f"{q} [{context}; prior: {excerpt[:240]}]"
    elif context:
        effective = f"{q} [{context}]"
    elif excerpt:
        effective = f"{q} [{excerpt[:280]}]"
    else:
        effective = q

    return TurnDeltaResult(
        effective_query=effective.strip(),
        information_need=need,
        sql_plan_hints=hints,
        resolver="deterministic_prior_state",
        reason=f"referential_{referential_kind}",
    )


def _invoke_delta_llm(
    *,
    question: str,
    prior: ConversationTurnState,
    prior_excerpt: str,
    referential_kind: ReferentialKind,
) -> TurnDeltaDecision | None:
    from app.config import config

    if not turn_delta_llm_enabled():
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.services.llm_factory import create_llm
        from app.services.observability.langfuse_service import get_langchain_callbacks

        model = (
            getattr(config, "TURN_DELTA_LLM_MODEL", None)
            or getattr(config, "CASE_ASSISTANT_ROUTER_MODEL", "")
            or "yandexgpt-lite/latest"
        )
        max_tokens = int(getattr(config, "TURN_DELTA_LLM_MAX_TOKENS", 384) or 384)
        llm = create_llm(model=model, temperature=0.0, max_tokens=max_tokens)
        structured = llm.with_structured_output(TurnDeltaDecision)
        callbacks = get_langchain_callbacks(tags=["assistant", "turn_delta"])

        prompt = (
            "Сформируй дельту для follow-up вопроса юриста.\n"
            "Опирайся на структурированное состояние прошлого turn и excerpt ответа.\n"
            "self_contained_query: полный запрос без местоимений.\n"
            "information_need: tabular_* для цифр выписки; document_narrative для смысла документа; "
            "document_drill_down для углубления в тот же документ.\n"
            "operation: только для tabular_* (count/sum/list/find); null = наследовать.\n"
            "inherit_period/inherit_file: true если период/файл не меняются.\n\n"
            f"Prior state:\n{prior.to_dict()}\n\n"
            f"Prior assistant excerpt:\n{(prior_excerpt or '[нет]')[:1200]}\n\n"
            f"Referential kind: {referential_kind}\n\n"
            f"New user question:\n{question.strip()}\n"
        )
        decision: TurnDeltaDecision = structured.invoke(
            [
                SystemMessage(
                    content=(
                        "Ты планировщик follow-up для юридического ассистента. "
                        "Не выдумывай факты — только перенос scope из prior state."
                    )
                ),
                HumanMessage(content=prompt),
            ],
            config={"callbacks": callbacks} if callbacks else None,
        )
        return decision
    except Exception as exc:
        logger.debug("[TurnDelta] LLM failed: %s", exc)
        return None


def resolve_turn_delta(
    *,
    question: str,
    prior_turn_state: ConversationTurnState,
    referential_kind: ReferentialKind = "none",
    prior_evidence: PriorTurnEvidence | None = None,
) -> TurnDeltaResult:
    q = (question or "").strip()
    excerpt = (prior_evidence.assistant_excerpt if prior_evidence else "") or ""

    llm = _invoke_delta_llm(
        question=q,
        prior=prior_turn_state,
        prior_excerpt=excerpt,
        referential_kind=referential_kind,
    )
    if llm is not None and llm.self_contained_query.strip():
        hints = merge_sql_plan_hints(
            prior_turn_state,
            operation_override=str(llm.operation or "").strip(),
            inherit_period=bool(llm.inherit_period),
            inherit_file=bool(llm.inherit_file),
        )
        if llm.operation:
            hints["operation"] = str(llm.operation)
        need_raw = str(llm.information_need or "unknown").strip().lower()
        need: InformationNeed = (
            need_raw
            if need_raw
            in {
                "tabular_aggregate",
                "tabular_list",
                "tabular_find",
                "document_narrative",
                "document_drill_down",
                "comparison",
                "unknown",
            }
            else "unknown"
        )
        return TurnDeltaResult(
            effective_query=llm.self_contained_query.strip(),
            information_need=need,
            sql_plan_hints=hints,
            resolver="llm",
            reason=(llm.rationale or "llm_delta")[:300],
        )

    return _deterministic_delta(
        question=q,
        prior=prior_turn_state,
        referential_kind=referential_kind,
        prior_excerpt=excerpt,
    )


def resolve_turn_delta_if_needed(
    *,
    question: str,
    prior_turn_state: Optional[ConversationTurnState],
    turn_context: Optional[Dict[str, object]],
    prior_evidence: PriorTurnEvidence | None = None,
) -> Optional[TurnDeltaResult]:
    if prior_turn_state is None:
        return None
    tc = turn_context if isinstance(turn_context, dict) else {}
    kind_raw = str(tc.get("referential_kind") or "none").strip().lower()
    kind: ReferentialKind = (
        kind_raw
        if kind_raw in {"none", "memory_synthesis", "scoped_deep_read", "citation_expand"}
        else "none"
    )
    if not _is_referential_follow_up(
        question,
        referential_kind=kind,
        has_prior_state=True,
        prior_turn_state=prior_turn_state,
    ):
        standalone = str(tc.get("standalone_query") or "").strip()
        original = str(tc.get("original_question") or question).strip()
        if standalone and standalone.lower() != original.lower():
            return None
        if kind == "none":
            return None
    return resolve_turn_delta(
        question=question,
        prior_turn_state=prior_turn_state,
        referential_kind=kind,
        prior_evidence=prior_evidence,
    )
