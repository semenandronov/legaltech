"""
LLM-планировщик retrieval по legal corpus (agentic RAG — фаза «понять вопрос»).

Основной путь: модель анализирует вопрос и формирует запросы к векторной БД.
Детерминированный план (legal_query_plan) — merge + fallback при ошибке LLM.

Ответ пользователю по-прежнему только из найденных фрагментов корпуса.
"""
from __future__ import annotations

import logging
import re
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.services.chat.legal_query_plan import (
    LegalRetrievalPlan,
    LegalRetrievalTopic,
    build_legal_retrieval_plan,
    extract_all_article_numbers,
)
from app.services.legal_instruments import INSTRUMENTS
from app.services.llm_factory import create_legal_llm
from app.services.observability.langfuse_service import get_langchain_callbacks

logger = logging.getLogger(__name__)

_VALID_TOPICS: Tuple[str, ...] = (
    "article_lookup",
    "challenge_transactions",
    "limitation_challenge",
    "general_bankruptcy",
    "general",
)

_VALID_INSTRUMENT_IDS = frozenset(
    iid for iid in INSTRUMENTS if iid not in ("other", "unknown")
)

_ARTICLE_RE = re.compile(r"^[0-9]{1,5}(?:\.[0-9]{1,3})?$")


class LegalCorpusRetrievalPlanLLM(BaseModel):
    """Structured output: план поиска по справочнику (не финальный ответ юристу)."""

    user_intent_summary: str = Field(
        default="",
        description="Кратко: что спрашивает пользователь и какой правовой результат нужен (1–2 предложения).",
    )
    topic: str = Field(
        default="general",
        description=(
            "article_lookup | challenge_transactions | limitation_challenge | "
            "general_bankruptcy | general"
        ),
    )
    instrument_ids: List[str] = Field(
        default_factory=list,
        description="Список id актов из реестра (fz-127, plenum-63, gk-rf, ...).",
    )
    required_articles: List[str] = Field(
        default_factory=list,
        description=(
            "Номера статей 127-ФЗ (или другого акта), без полного текста которых нельзя ответить "
            "(например 61.2, 213.4, 223.2 — по смыслу вопроса, не по шаблону)."
        ),
    )
    search_queries: List[str] = Field(
        default_factory=list,
        description="3–6 коротких поисковых фраз для hybrid/FTS (5–18 слов, русский).",
    )
    rationale: str = Field(
        default="",
        description="Кратко для логов: почему выбраны эти акты и статьи.",
    )

    @field_validator("required_articles", mode="before")
    @classmethod
    def _norm_articles(cls, v: object) -> List[str]:
        if not v:
            return []
        out: List[str] = []
        seen: set[str] = set()
        for raw in v if isinstance(v, list) else []:
            a = str(raw).strip().replace(",", ".")
            if _ARTICLE_RE.match(a) and a not in seen:
                seen.add(a)
                out.append(a)
        return out[:12]

    @field_validator("instrument_ids", mode="before")
    @classmethod
    def _norm_instruments(cls, v: object) -> List[str]:
        if not v:
            return []
        out: List[str] = []
        seen: set[str] = set()
        for raw in v if isinstance(v, list) else []:
            iid = str(raw).strip().lower()
            if iid in _VALID_INSTRUMENT_IDS and iid not in seen:
                seen.add(iid)
                out.append(iid)
        return out


def _llm_planner_enabled() -> bool:
    return bool(getattr(config, "LEGAL_CORPUS_LLM_PLANNER_ENABLED", True))


def _instruments_catalog_blurb() -> str:
    lines = []
    for iid in sorted(_VALID_INSTRUMENT_IDS):
        inst = INSTRUMENTS[iid]
        lines.append(f"- {iid}: {inst.title} (алиасы: {', '.join(inst.aliases[:4])})")
    return "\n".join(lines)


def _planner_system_prompt(*, max_queries: int, legal_research: bool) -> str:
    """Инструкция планировщику: весь 127‑ФЗ и смежные акты, без перечисления частных кейсов."""
    sys = (
        "Ты — планировщик поиска по правовому справочнику банкротства (legal_corpus).\n"
        "Тебе дан вопрос пользователя. Ты НЕ отвечаешь на вопрос — только планируешь извлечение "
        "норм из векторной базы для последующего ответа юриста.\n\n"
        "Метод (по шагам):\n"
        "1) Определи правовой институт и результат, который нужен пользователю (1–2 предложения в user_intent_summary).\n"
        "2) Выбери акты (instrument_id) из списка ниже. Ядро — fz-127 (127‑ФЗ о банкротстве); "
        "plenum-63 — при оспаривании сделок; gk-rf / apk-rf / gpk-rf — если вопрос явно про смежные нормы.\n"
        "3) Укажи required_articles — номера статей, без полного текста которых ответ будет неполным "
        "(конкретные статьи и подпункты 127‑ФЗ: гл. о гражданине, внесудебное, оспаривание сделок, ФУ, реестр и т.д.).\n"
        "4) Сформируй search_queries — короткие поисковые фразы (не пересказ вопроса), с номерами статей и ключевыми "
        "терминами из 127‑ФЗ, если знаешь их.\n\n"
        "Доступные акты (instrument_id):\n"
        f"{_instruments_catalog_blurb()}\n\n"
        "Правила:\n"
        "- topic: article_lookup — если пользователь явно спросил текст/смысл конкретной статьи; "
        "challenge_transactions — оспаривание/подозрительные/предпочтительные сделки; "
        "limitation_challenge — сроки или исковая давность по оспариванию сделок; "
        "general_bankruptcy — любой другой вопрос по 127‑ФЗ (внесудебное, гражданин, реестр, ФУ, МФЦ, субсидиарка и т.д.); "
        "general — вне банкротства.\n"
        "- Не подставляй статьи «по умолчанию»: required_articles только те, что нужны для ЭТОГО вопроса.\n"
        "- Слово «лимит» само по себе не означает оспаривание сделок — смотри на институт (долг, процедура, полномочия, срок и т.д.).\n"
        "- instrument_id только из списка; при сомнении по банкротству — fz-127.\n"
        f"- Не более {max_queries} search_queries.\n"
        "- Финальный ответ системы строится ТОЛЬКО по найденным фрагментам; твоя задача — максимально точно нацелить поиск.\n"
    )
    if legal_research:
        sys += "\nКонтекст: режим правового справочника (legal_research).\n"
    return sys


def plan_legal_corpus_retrieval_llm(
    question: str,
    *,
    legal_research: bool = False,
) -> Optional[LegalCorpusRetrievalPlanLLM]:
    """
    LLM анализирует вопрос и планирует поиск по legal_corpus.
    Fail-open: None при ошибке или отключении.
    """
    if not _llm_planner_enabled():
        return None

    q = (question or "").strip()
    if not q:
        return None

    max_q = max(3, min(8, int(getattr(config, "LEGAL_CORPUS_LLM_PLANNER_MAX_QUERIES", 6) or 6)))
    model_name = (getattr(config, "LEGAL_CORPUS_LLM_PLANNER_MODEL", "") or "").strip()

    llm_kwargs: dict = {
        "use_rate_limiting": False,
        "temperature": 0.0,
        "max_tokens": 700,
    }
    if model_name:
        llm_kwargs["model"] = model_name
    llm = create_legal_llm(**llm_kwargs)

    sys = _planner_system_prompt(max_queries=max_q, legal_research=legal_research)

    callbacks = get_langchain_callbacks(tags=["assistant", "legal_corpus", "retrieval_planner"])
    try:
        if not hasattr(llm, "with_structured_output"):
            logger.warning("[LegalRetrievalPlanner] structured_output unavailable")
            return None
        judge = llm.with_structured_output(LegalCorpusRetrievalPlanLLM)
        result = judge.invoke(
            [SystemMessage(content=sys), HumanMessage(content=q)],
            config={"callbacks": callbacks} if callbacks else None,
        )
        if not isinstance(result, LegalCorpusRetrievalPlanLLM):
            return None

        # cap queries
        seen_q: set[str] = set()
        capped: List[str] = []
        for sq in result.search_queries or []:
            t = str(sq).strip()
            if not t or len(t) > 220:
                continue
            low = t.lower()
            if low in seen_q:
                continue
            seen_q.add(low)
            capped.append(t)
            if len(capped) >= max_q:
                break
        result.search_queries = capped
        logger.info(
            "[LegalRetrievalPlanner] LLM plan topic=%s instruments=%s articles=%s queries=%d",
            result.topic,
            result.instrument_ids,
            result.required_articles,
            len(capped),
        )
        return result
    except Exception as ex:
        logger.warning("[LegalRetrievalPlanner] LLM planner failed (fail-open): %s", ex)
        return None


def _normalize_topic(raw: str, fallback: LegalRetrievalTopic) -> LegalRetrievalTopic:
    t = (raw or "").strip().lower()
    if t in _VALID_TOPICS:
        return t  # type: ignore[return-value]
    return fallback


def _merge_plans(
    question: str,
    det: LegalRetrievalPlan,
    llm: Optional[LegalCorpusRetrievalPlanLLM],
) -> Tuple[LegalRetrievalPlan, str]:
    """
    Объединить LLM-план (приоритет запросов) с детерминированным (покрытие edge cases).
    """
    if not llm:
        return det, "deterministic"

    topic = _normalize_topic(llm.topic, det.topic)
    instruments: List[str] = []
    seen_i: set[str] = set()
    for iid in list(llm.instrument_ids or []) + list(det.instrument_ids or []):
        if iid in _VALID_INSTRUMENT_IDS and iid not in seen_i:
            seen_i.add(iid)
            instruments.append(iid)

    required: List[str] = []
    seen_a: set[str] = set()
    for art in list(extract_all_article_numbers(question)) + list(llm.required_articles or []) + list(
        det.required_articles or []
    ):
        a = str(art).strip()
        if _ARTICLE_RE.match(a) and a not in seen_a:
            seen_a.add(a)
            required.append(a)

    queries: List[str] = []
    seen_q: set[str] = set()
    for sq in list(llm.search_queries or []) + list(det.search_queries or []):
        t = (sq or "").strip()
        if not t:
            continue
        low = t.lower()
        if low in seen_q:
            continue
        seen_q.add(low)
        queries.append(t)

    cap = max(4, min(12, int(getattr(config, "LEGAL_CORPUS_MAX_HYBRID_QUERIES", 3) or 3) + 5))
    if len(queries) > cap:
        queries = queries[:cap]

    rationale_parts = [
        f"planner=merged",
        (llm.rationale or "").strip()[:300],
        det.rationale,
    ]
    if llm.user_intent_summary:
        rationale_parts.insert(1, f"intent={llm.user_intent_summary[:200]}")

    merged = LegalRetrievalPlan(
        topic=topic,
        required_articles=required,
        instrument_ids=instruments or det.instrument_ids,
        search_queries=queries or det.search_queries,
        rationale="; ".join(p for p in rationale_parts if p),
        user_articles=list(det.user_articles) or extract_all_article_numbers(question),
    )
    return merged, "llm+deterministic"


def resolve_legal_retrieval_plan(
    question: str,
    *,
    instrument_ids: Optional[List[str]] = None,
    legal_research: bool = False,
    task_type: Optional[str] = None,
) -> Tuple[LegalRetrievalPlan, str]:
    """
    Единая точка планирования: LLM (если включён) + merge с детерминированным fallback.
    Returns: (plan, planner_source) where planner_source is llm+deterministic | deterministic
    """
    pre = [x for x in (instrument_ids or []) if x and x != "unknown"]
    det = build_legal_retrieval_plan(
        question,
        instrument_ids=pre,
        legal_research=legal_research,
        task_type=task_type,
    )
    llm_plan = plan_legal_corpus_retrieval_llm(question, legal_research=legal_research)
    return _merge_plans(question, det, llm_plan)
