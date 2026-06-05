"""
Court practice query planner (multi-query) for cad_precedents retrieval.

Goal: given a user question, produce a small set of *lexical-friendly* search queries
to widen FTS recall without multiplying embedding calls (Giga embeddings are expensive).
"""

from __future__ import annotations

import logging
import re
from typing import List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import config
from app.services.llm_factory import create_legal_llm
from app.services.observability.langfuse_service import get_langchain_callbacks

logger = logging.getLogger(__name__)


class CourtPracticePlanLLM(BaseModel):
    """Structured output: query expansion plan for court_practice retrieval."""

    search_queries: List[str] = Field(
        default_factory=list,
        description="3–8 коротких поисковых фраз для FTS/lexical по судебной практике (5–18 слов, русский).",
    )
    rationale: str = Field(default="", description="Коротко для логов.")


_BANKRUPTCY_HINTS: Tuple[Tuple[str, List[str]], ...] = (
    (
        "субсидиар",
        [
            "субсидиарная ответственность контролирующее лицо",
            "статья 61.11 127-ФЗ субсидиарная ответственность",
            "пункт 4 статьи 10 127-ФЗ контролирующее лицо",
        ],
    ),
    (
        "контролир",
        [
            "контролирующее лицо 61.10 127-ФЗ критерии",
            "привлечение к субсидиарной ответственности 61.11 127-ФЗ",
        ],
    ),
    (
        "непередач",
        [
            "непередача документов конкурсному управляющему 61.11",
            "отсутствие бухгалтерских документов субсидиарная ответственность",
        ],
    ),
    (
        "оспарив",
        [
            "оспаривание сделки должника 61.2 61.3 127-ФЗ",
            "признание сделки недействительной банкротство 61.2",
        ],
    ),
    (
        "предпочт",
        [
            "предпочтительное удовлетворение 61.3 127-ФЗ",
            "предпочтительная сделка 61.3 банкротство",
        ],
    ),
    (
        "подозр",
        [
            "подозрительная сделка 61.2 127-ФЗ",
            "неравноценное встречное исполнение 61.2 банкротство",
        ],
    ),
    (
        "давност",
        [
            "срок исковой давности субсидиарная 61.11 127-ФЗ",
            "срок подачи заявления о субсидиарной ответственности 61.11",
        ],
    ),
)


def _dedupe_cap(queries: List[str], *, cap: int) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for q in queries:
        t = (q or "").strip()
        if not t or len(t) > 240:
            continue
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
        if len(out) >= cap:
            break
    return out


def build_court_practice_search_queries(question: str) -> List[str]:
    """
    Deterministic expansion: low-latency, no external calls.
    Returns: list including the original question (for FTS).
    """

    q = (question or "").strip()
    if not q:
        return []
    ql = q.lower()
    raw: List[str] = [q]
    for marker, variants in _BANKRUPTCY_HINTS:
        if marker in ql:
            raw.extend(variants)

    # If user mentioned a case number, keep it as a standalone search token.
    m = re.search(r"\b[АA]\d{1,2}-\d{2,7}/\d{2,4}\b", q.upper())
    if m:
        raw.insert(0, m.group(0))

    cap = max(2, min(10, int(getattr(config, "COURT_PRACTICE_QUERY_PLANNER_MAX_QUERIES", 6) or 6)))
    return _dedupe_cap(raw, cap=cap)


def plan_court_practice_search_queries(question: str) -> Tuple[List[str], str]:
    """
    LLM + deterministic merge. Fail-open to deterministic-only.
    Returns: (search_queries, rationale_for_logs)
    """
    import time

    from app.services.observability.court_practice_langfuse_tracing import (
        court_practice_span,
        trace_planner_result,
    )

    base = build_court_practice_search_queries(question)
    if not bool(getattr(config, "COURT_PRACTICE_LLM_PLANNER_ENABLED", True)):
        trace_planner_result(
            question=question,
            search_queries=base,
            planner_source="deterministic",
            rationale="llm_planner_disabled",
        )
        return base, "llm_planner_disabled"

    q = (question or "").strip()
    if not q:
        return [], "empty_question"

    max_q = max(3, min(10, int(getattr(config, "COURT_PRACTICE_QUERY_PLANNER_MAX_QUERIES", 6) or 6)))
    model_name = (getattr(config, "COURT_PRACTICE_LLM_PLANNER_MODEL", "") or "").strip()

    llm_kwargs: dict = {"use_rate_limiting": False, "temperature": 0.0, "max_tokens": 500}
    if model_name:
        llm_kwargs["model"] = model_name
    llm = create_legal_llm(**llm_kwargs)

    sys = (
        "Ты — эксперт по подбору судебной практики в делах о банкротстве.\n"
        "Тебе дан вопрос пользователя.\n"
        "Ты НЕ отвечаешь на вопрос. Ты формируешь короткие поисковые фразы для полнотекстового поиска (FTS) "
        "по базе судебных актов.\n\n"
        "Правила:\n"
        "- Верни 3–8 поисковых фраз, 5–18 слов, русский язык.\n"
        "- Используй юридические термины, близкие формулировки и номера статей, если уместно (61.10, 61.11, п.4 ст.10 и т.д.).\n"
        "- Не выдумывай номера дел или даты.\n"
        "- Одна фраза = один аспект вопроса.\n"
        f"- Не более {max_q} фраз.\n"
    )

    callbacks = get_langchain_callbacks(tags=["assistant", "court_practice", "retrieval_planner"])
    t0 = time.monotonic()
    with court_practice_span(
        "query_planner",
        input_payload={"question": q[:800], "deterministic_queries": base[:8]},
        metadata={"llm_enabled": True, "max_queries": max_q},
    ) as planner_out:
        try:
            if not hasattr(llm, "with_structured_output"):
                planner_out["planner_source"] = "structured_output_unavailable"
                trace_planner_result(
                    question=q,
                    search_queries=base,
                    planner_source="deterministic",
                    rationale="structured_output_unavailable",
                    latency_ms=int((time.monotonic() - t0) * 1000),
                )
                return base, "structured_output_unavailable"
            judge = llm.with_structured_output(CourtPracticePlanLLM)
            result = judge.invoke(
                [SystemMessage(content=sys), HumanMessage(content=q)],
                config={"callbacks": callbacks} if callbacks else None,
            )
            if not isinstance(result, CourtPracticePlanLLM):
                planner_out["planner_source"] = "unexpected_planner_type"
                trace_planner_result(
                    question=q,
                    search_queries=base,
                    planner_source="deterministic",
                    rationale="unexpected_planner_type",
                    latency_ms=int((time.monotonic() - t0) * 1000),
                )
                return base, "unexpected_planner_type"
            merged = _dedupe_cap(list(base) + list(result.search_queries or []), cap=max_q)
            rationale = (result.rationale or "").strip()[:240]
            planner_out["planner_source"] = "llm+deterministic"
            planner_out["search_queries"] = merged
            planner_out["llm_queries_count"] = len(result.search_queries or [])
            logger.info("[CourtPracticePlanner] queries=%d q=%s", len(merged), q[:80])
            trace_planner_result(
                question=q,
                search_queries=merged,
                planner_source="llm+deterministic",
                rationale=rationale or "llm_ok",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
            return merged, rationale or "llm_ok"
        except Exception as ex:
            logger.warning("[CourtPracticePlanner] LLM planner failed (fail-open): %s", ex)
            planner_out["planner_source"] = "llm_exception"
            planner_out["error"] = str(ex)[:300]
            trace_planner_result(
                question=q,
                search_queries=base,
                planner_source="deterministic",
                rationale="llm_exception",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
            return base, "llm_exception"

