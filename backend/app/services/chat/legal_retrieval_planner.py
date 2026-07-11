"""
LLM-планировщик retrieval по legal corpus (agentic RAG — фаза «понять вопрос»).

Модель извлекает факты и короткие search_queries; номера статей не угадывает.
Явные статьи из вопроса — детерминированный merge (extract_all_article_numbers).

Ответ пользователю по-прежнему только из найденных фрагментов корпуса.
"""
from __future__ import annotations

import json
import logging
import re
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.services.chat.legal_query_plan import (
    LegalRetrievalPlan,
    LegalRetrievalTopic,
    allowed_user_article_numbers,
    build_legal_retrieval_plan,
    extract_all_article_numbers,
    is_near_duplicate_of_question,
    sanitize_planner_search_query,
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
    """Structured output: факты + поисковые фразы (не финальный ответ юристу)."""

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
    facts: List[str] = Field(
        default_factory=list,
        description=(
            "3–6 коротких фактов из вопроса: субъект, институт, пороги, сроки, процедура "
            "(без номеров статей, если пользователь их не назвал)."
        ),
    )
    clause_ref: str = Field(
        default="",
        description=(
            "Если пользователь спрашивает про конкретный пункт статьи — номер пункта "
            "(например «3» или «1.1»). Пусто — нужна вся статья целиком."
        ),
    )
    search_queries: List[str] = Field(
        default_factory=list,
        description=(
            "3–5 коротких поисковых фраз для hybrid/FTS (8–14 слов). "
            "Формулировки на языке 127-ФЗ (термины закона о несостоятельности), без номеров статей."
        ),
    )
    rationale: str = Field(
        default="",
        description="Кратко для логов: почему выбраны акты и поисковые фразы.",
    )

    @field_validator("facts", mode="before")
    @classmethod
    def _norm_facts(cls, v: object) -> List[str]:
        if not v:
            return []
        out: List[str] = []
        seen: set[str] = set()
        for raw in v if isinstance(v, list) else []:
            t = str(raw).strip()
            if not t or len(t) > 180:
                continue
            low = t.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append(t)
        return out[:8]

    @field_validator("clause_ref", mode="before")
    @classmethod
    def _norm_clause_ref(cls, v: object) -> str:
        if v is None:
            return ""
        s = str(v).strip().replace(",", ".")
        if not s:
            return ""
        parts = s.split(".")
        if all(p.isdigit() for p in parts if p):
            return s
        return ""

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


def _planner_timeout_sec() -> float:
    return max(3.0, float(getattr(config, "LEGAL_CORPUS_PLANNER_TIMEOUT_SEC", 20) or 20))


def _parse_planner_json_payload(raw: str) -> Optional[LegalCorpusRetrievalPlanLLM]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except Exception:
        try:
            return LegalCorpusRetrievalPlanLLM.model_validate_json(text)
        except Exception:
            return None
    if isinstance(data, dict):
        # Обратная совместимость: старый ключ required_articles → facts (не мержим как статьи)
        if "facts" not in data and data.get("required_articles"):
            legacy = [str(a) for a in data["required_articles"] if a]
            data = {**data, "facts": [f"статья {a} 127-ФЗ" for a in legacy[:4]]}
        data.pop("required_articles", None)
    try:
        return LegalCorpusRetrievalPlanLLM.model_validate(data)
    except Exception:
        return None


def _instruments_catalog_blurb() -> str:
    lines = []
    for iid in sorted(_VALID_INSTRUMENT_IDS):
        inst = INSTRUMENTS[iid]
        lines.append(f"- {iid}: {inst.title} (алиасы: {', '.join(inst.aliases[:4])})")
    return "\n".join(lines)


def _bankruptcy_legal_lexicon_blurb() -> str:
    """Термины 127-ФЗ для search_queries (без номеров статей)."""
    return (
        "Лексика 127-ФЗ для search_queries (используй формулировки из закона, не бытовой русский):\n"
        "- субъекты: должник, юридическое лицо, гражданин, конкурсный кредитор, уполномоченный орган\n"
        "- институты: несостоятельность банкротство, возбуждение производства по делу о банкротстве, "
        "признание должника банкротом, принятие заявления арбитражным судом\n"
        "- юрлицо: признаки банкротства юридического лица, неспособность удовлетворить требования кредиторов, "
        "совокупность требований, денежные обязательства, обязательные платежи\n"
        "- гражданин: возбуждение производства по делу о банкротстве гражданина, "
        "заявление конкурсного кредитора о признании гражданина банкротом\n"
        "- пороги (если уместно по вопросу): не менее двух миллионов рублей (юрлицо), "
        "не менее пятьсот тысяч рублей (гражданин), три месяца просрочки исполнения обязательств\n"
        "- оспаривание: подозрительная сделка, неравноценная сделка, финансовый управляющий\n"
        "Плохо: «порог задолженности физлица», «признаки банкротства гражданина» без процессуального контекста.\n"
        "Хорошо: «заявление конкурсного кредитора возбуждение банкротства гражданина требования пятьсот тысяч рублей».\n"
    )


def _planner_system_prompt(*, max_queries: int, legal_research: bool) -> str:
    """Инструкция: извлечь факты и короткие поисковые фразы на языке 127-ФЗ."""
    sys = (
        "Ты — планировщик поиска по правовому справочнику банкротства (legal_corpus).\n"
        "Тебе дан вопрос пользователя. Ты НЕ отвечаешь на вопрос — только планируешь извлечение "
        "норм из векторной базы для последующего ответа юриста.\n\n"
        "Метод (по шагам):\n"
        "1) user_intent_summary — правовой институт и результат, который нужен (1–2 предложения).\n"
        "2) facts — 3–6 коротких фактов из вопроса: субъект (юрлицо/гражданин), институт, "
        "пороги, суммы, сроки, процедура. НЕ указывай номера статей, если пользователь их не назвал.\n"
        "3) instrument_ids — акты из списка ниже (ядро fz-127; plenum-63 при оспаривании сделок).\n"
        "4) search_queries — 3–5 коротких фраз для векторного/FTS поиска (8–14 слов). "
        "Каждая фраза — отдельный поисковый запрос; НЕ копируй весь вопрос целиком.\n"
        "   search_queries пиши на ЮРИДИЧЕСКОМ языке 127-ФЗ: термины из закона о несостоятельности, "
        "как в тексте норм (см. лексикон ниже). Не используй разговорные синонимы («физлицо», «порог долга»).\n"
        "   При сравнении гражданина и юрлица — минимум одна фраза на каждый субъект отдельно.\n"
        "   ЗАПРЕЩЕНО писать «статья N» / «ст. N» в search_queries, если пользователь не назвал N.\n"
        "   Примеры фраз:\n"
        "   • «признаки банкротства юридического лица неспособность удовлетворить требования кредиторов три месяца»\n"
        "   • «возбуждение производства банкротство гражданина заявление конкурсного кредитора пятьсот тысяч рублей»\n"
        "   • «принятие заявления арбитражным судом совокупность требований два миллиона рублей юридическое лицо»\n\n"
        f"{_bankruptcy_legal_lexicon_blurb()}\n"
        "Доступные акты (instrument_id):\n"
        f"{_instruments_catalog_blurb()}\n\n"
        "Правила:\n"
        "- topic: article_lookup — только если пользователь явно спросил текст/смысл конкретной статьи "
        "или пункта; clause_ref — номер пункта при вопросе про пункт; "
        "challenge_transactions — оспаривание сделок; limitation_challenge — сроки оспаривания; "
        "general_bankruptcy — любой другой вопрос по 127‑ФЗ; general — вне банкротства.\n"
        "- НЕ угадывай номера статей — ни в facts, ни в search_queries; поиск найдёт нормы по терминам закона.\n"
        "- instrument_id только из списка; при сомнении по банкротству — fz-127.\n"
        f"- Не более {max_queries} search_queries.\n"
        "- Финальный ответ строится ТОЛЬКО по найденным фрагментам.\n"
        "- Ответ — только один JSON-объект (без markdown): user_intent_summary, topic, "
        "instrument_ids, facts, clause_ref, search_queries, rationale.\n"
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
    LLM извлекает факты и search_queries для legal_corpus.
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
        "timeout": _planner_timeout_sec(),
        "model_kwargs": {"reasoning_effort": "none"},
    }
    if model_name:
        llm_kwargs["model"] = model_name
    llm = create_legal_llm(**llm_kwargs)

    sys = _planner_system_prompt(max_queries=max_q, legal_research=legal_research)

    callbacks = get_langchain_callbacks(tags=["assistant", "legal_corpus", "retrieval_planner"])
    try:
        runnable = llm.bind(response_format={"type": "json_object"})
        response = runnable.invoke(
            [SystemMessage(content=sys), HumanMessage(content=q)],
            config={"callbacks": callbacks} if callbacks else None,
        )
        raw = (getattr(response, "content", None) or "").strip()
        result = _parse_planner_json_payload(raw)
        if not isinstance(result, LegalCorpusRetrievalPlanLLM):
            logger.warning("[LegalRetrievalPlanner] invalid JSON payload from LLM")
            return None

        seen_q: set[str] = set()
        capped: List[str] = []
        allowed = allowed_user_article_numbers(q)
        for sq in result.search_queries or []:
            cleaned = sanitize_planner_search_query(str(sq).strip(), allowed)
            if not cleaned or len(cleaned) > 220:
                continue
            if is_near_duplicate_of_question(cleaned, q):
                continue
            low = cleaned.lower()
            if low in seen_q:
                continue
            seen_q.add(low)
            capped.append(cleaned)
            if len(capped) >= max_q:
                break
        result.search_queries = capped
        logger.info(
            "[LegalRetrievalPlanner] LLM plan topic=%s instruments=%s facts=%d queries=%d",
            result.topic,
            result.instrument_ids,
            len(result.facts or []),
            len(capped),
        )
        return result
    except Exception as ex:
        logger.warning("[LegalRetrievalPlanner] LLM planner failed (fail-open): %s", ex)
        return None


_TOPIC_RANK: dict[str, int] = {
    "general": 1,
    "general_bankruptcy": 2,
    "limitation_challenge": 3,
    "challenge_transactions": 3,
    "article_lookup": 4,
}


def _normalize_topic(raw: str, fallback: LegalRetrievalTopic) -> LegalRetrievalTopic:
    t = (raw or "").strip().lower()
    if t in _VALID_TOPICS:
        return t  # type: ignore[return-value]
    return fallback


def _pick_topic(llm_topic: str, det_topic: LegalRetrievalTopic) -> LegalRetrievalTopic:
    """Берём более специфичный topic (детерминированный банкротный контекст не теряем)."""
    lt = _normalize_topic(llm_topic, det_topic)
    rank_l = _TOPIC_RANK.get(lt, 0)
    rank_d = _TOPIC_RANK.get(det_topic, 0)
    return det_topic if rank_d > rank_l else lt


def _user_articles_only(question: str, det: LegalRetrievalPlan) -> List[str]:
    """Статьи плана — только явно из текста пользователя."""
    required: List[str] = []
    seen_a: set[str] = set()
    for art in list(det.user_articles or []) + list(extract_all_article_numbers(question)):
        a = str(art).strip()
        if _ARTICLE_RE.match(a) and a not in seen_a:
            seen_a.add(a)
            required.append(a)
    return required


def _merge_plans(
    question: str,
    det: LegalRetrievalPlan,
    llm: Optional[LegalCorpusRetrievalPlanLLM],
) -> Tuple[LegalRetrievalPlan, str]:
    """
    LLM даёт facts + search_queries; статьи и clause — только из вопроса пользователя.
    """
    if not llm:
        return det, "deterministic"

    topic = _pick_topic(llm.topic, det.topic)
    instruments: List[str] = []
    seen_i: set[str] = set()
    for iid in list(llm.instrument_ids or []) + list(det.instrument_ids or []):
        if iid in _VALID_INSTRUMENT_IDS and iid not in seen_i:
            seen_i.add(iid)
            instruments.append(iid)

    required = _user_articles_only(question, det)
    allowed = allowed_user_article_numbers(question, det)

    queries: List[str] = []
    seen_q: set[str] = set()
    llm_short_count = 0
    for sq in list(llm.search_queries or []):
        cleaned = sanitize_planner_search_query(sq, allowed)
        if not cleaned or is_near_duplicate_of_question(cleaned, question):
            continue
        low = cleaned.lower()
        if low in seen_q:
            continue
        seen_q.add(low)
        queries.append(cleaned)
        llm_short_count += 1

    min_llm_before_skip_det = max(
        2, int(getattr(config, "LEGAL_CORPUS_PLANNER_MIN_QUERIES_SKIP_ROUTE", 3) or 3)
    )
    skip_det_queries = llm_short_count >= min_llm_before_skip_det
    if not skip_det_queries:
        for sq in list(det.search_queries or []):
            t = (sq or "").strip()
            if not t or is_near_duplicate_of_question(t, question):
                continue
            cleaned = sanitize_planner_search_query(t, allowed)
            if not cleaned:
                continue
            low = cleaned.lower()
            if low in seen_q:
                continue
            seen_q.add(low)
            queries.append(cleaned)

    cap = max(4, min(12, int(getattr(config, "LEGAL_CORPUS_MAX_HYBRID_QUERIES", 3) or 3) + 5))
    if len(queries) > cap:
        queries = queries[:cap]

    facts: List[str] = []
    seen_f: set[str] = set()
    for f in list(llm.facts or []):
        t = sanitize_planner_search_query(f, allowed)
        if not t:
            continue
        low = t.lower()
        if low in seen_f:
            continue
        seen_f.add(low)
        facts.append(t)

    rationale_parts = [
        "planner=merged",
        (llm.rationale or "").strip()[:300],
        det.rationale,
    ]
    if llm.user_intent_summary:
        rationale_parts.insert(1, f"intent={llm.user_intent_summary[:200]}")

    from app.services.legal_norm_cross_ref import normalize_article_number

    user_clause_ref = normalize_article_number(llm.clause_ref or "") if llm else ""
    user_articles = _user_articles_only(question, det)

    merged = LegalRetrievalPlan(
        topic=topic,
        required_articles=required,
        instrument_ids=instruments or det.instrument_ids,
        search_queries=queries or det.search_queries,
        rationale="; ".join(p for p in rationale_parts if p),
        user_articles=user_articles,
        user_clause_ref=user_clause_ref or det.user_clause_ref,
        facts=facts,
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
