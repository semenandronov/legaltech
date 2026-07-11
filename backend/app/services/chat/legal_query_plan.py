"""
Детерминированный план retrieval (fallback / merge) для legal corpus.

Основной планировщик — legal_retrieval_planner.resolve_legal_retrieval_plan (LLM).
Этот модуль: правила домена 127‑ФЗ, покрытие статей, coverage — без LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Sequence, Tuple

from app.config import config
from app.services.legal_norm_cross_ref import normalize_article_number

LegalRetrievalTopic = Literal[
    "article_lookup",
    "challenge_transactions",
    "limitation_challenge",
    "general_bankruptcy",
    "general",
]

_REPEAL_MARKERS: Tuple[str, ...] = (
    "утратил силу",
    "утратила силу",
    "утратили силу",
    "исключена",
    "исключён",
    "не действует",
    "недействует",
)

_CHALLENGE_MARKERS: Tuple[str, ...] = (
    "оспарив",
    "оспорить",
    "оспорим",
    "подозрительн",
    "неравноцен",
    "предпочтит",
    "предпочтен",
    "злоупотреблен",
    "сделк",
    "отчужд",
)

_LIMITATION_MARKERS: Tuple[str, ...] = (
    "срок",
    "период",
    "исковая давность",
    "давност",
    "в течение какого",
    "за какой период",
)

_MANAGER_MARKERS: Tuple[str, ...] = (
    "финансовый управляющ",
    "конкурсный управляющ",
    "арбитражный управляющ",
    "временный управляющ",
)


@dataclass(frozen=True)
class LegalRetrievalPlan:
    topic: LegalRetrievalTopic
    required_articles: List[str]
    instrument_ids: List[str]
    search_queries: List[str]
    rationale: str
    user_articles: List[str] = field(default_factory=list)
    user_clause_ref: str = ""
    facts: List[str] = field(default_factory=list)


def extract_all_article_numbers(query: str) -> List[str]:
    """Все номера статей из вопроса (ст. 61 и 62 → ['61','62'])."""
    q = (query or "").strip()
    if not q:
        return []
    found: List[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"(?:ст\.?|статья|статьи|ст\.)\s*([0-9]{1,5}(?:\.[0-9]{1,3})?)", q, re.I):
        art = m.group(1)
        if art not in seen:
            seen.add(art)
            found.append(art)
    # «61 и 62» без слова «статья»
    for m in re.finditer(
        r"(?:ст\.?|статья|статьи)\s*([0-9]{1,5}(?:\.[0-9]{1,3})?)\s*(?:и|,)\s*([0-9]{1,5}(?:\.[0-9]{1,3})?)",
        q,
        re.I,
    ):
        for g in (m.group(1), m.group(2)):
            if g and g not in seen:
                seen.add(g)
                found.append(g)
    return found


def _has_any(ql: str, needles: Sequence[str]) -> bool:
    return any(n in ql for n in needles)


def _dedupe_queries(queries: Sequence[str], *, cap: int) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in queries:
        t = (raw or "").strip()
        if not t:
            continue
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
        if len(out) >= cap:
            break
    return out


def _topic_challenge_transactions(ql: str) -> bool:
    if not _has_any(ql, _CHALLENGE_MARKERS):
        return False
    return _has_any(ql, _MANAGER_MARKERS) or "должник" in ql or "банкрот" in ql


def _topic_limitation_challenge(ql: str) -> bool:
    return _has_any(ql, _LIMITATION_MARKERS) and (
        _has_any(ql, _CHALLENGE_MARKERS) or "оспарив" in ql or "сделк" in ql
    )


def _articles_for_topic(topic: LegalRetrievalTopic) -> List[str]:
    """Статьи из плана — только из вопроса и LLM; без захардкоженных пакетов."""
    return []


def _queries_for_topic(topic: LegalRetrievalTopic, ql: str) -> List[str]:
    """Поисковые запросы по теме — формирует LLM-планировщик, не детерминированный fallback."""
    return []


def build_legal_retrieval_plan(
    question: str,
    *,
    instrument_ids: List[str],
    route_queries: Optional[List[str]] = None,
    legal_research: bool = False,
    task_type: Optional[str] = None,
) -> LegalRetrievalPlan:
    """
    План до retrieval: topic, обязательные статьи, расширенные search queries.
    """
    from app.services.chat.legal_router import extract_article_number, resolve_legal_corpus_route

    q = (question or "").strip()
    ql = q.lower()
    ids = [x for x in instrument_ids if x and x != "unknown"]

    if not ids:
        route = resolve_legal_corpus_route(q, legal_research=legal_research, task_type=task_type)
        ids = [x for x in route.instrument_ids if x and x != "unknown"]
        route_queries = list(route.queries)
        route_rationale = route.rationale
    else:
        route_rationale = "caller_instrument_ids"

    user_articles = extract_all_article_numbers(q)
    if not user_articles:
        single = extract_article_number(q)
        if single:
            user_articles = [single]

    topic: LegalRetrievalTopic = "general"
    rationale_parts: List[str] = [route_rationale]

    if user_articles and not _topic_challenge_transactions(ql) and not _topic_limitation_challenge(ql):
        topic = "article_lookup"
        rationale_parts.append(f"явные статьи: {', '.join(user_articles)}")
    elif _topic_limitation_challenge(ql):
        topic = "limitation_challenge"
        rationale_parts.append("сроки/период оспаривания сделок")
    elif _topic_challenge_transactions(ql):
        topic = "challenge_transactions"
        rationale_parts.append("оспаривание сделок должника")
    elif "банкрот" in ql or "127" in ql or "фз-127" in ql or "фз 127" in ql:
        topic = "general_bankruptcy"
        rationale_parts.append("банкротный контекст без узкой темы")

    required: List[str] = list(user_articles)
    for art in _articles_for_topic(topic):
        if art not in required:
            required.append(art)

    queries: List[str] = list(route_queries or [])
    queries.extend(_queries_for_topic(topic, ql))
    for art in user_articles:
        queries.append(f"статья {art} 127-ФЗ")
        queries.append(f"ст. {art} ФЗ о несостоятельности")

    cap = max(4, min(10, int(getattr(config, "LEGAL_CORPUS_MAX_HYBRID_QUERIES", 3) or 3) + 3))
    search_queries = _dedupe_queries(queries, cap=cap)

    return LegalRetrievalPlan(
        topic=topic,
        required_articles=required,
        instrument_ids=ids,
        search_queries=search_queries,
        rationale="; ".join(rationale_parts),
        user_articles=list(user_articles),
    )


def doc_metadata_matches_article(doc: object, article: str) -> bool:
    """Точное совпадение article_number в метаданных чанка (без regex по тексту)."""
    if not article:
        return False
    meta = getattr(doc, "metadata", None) or {}
    if not isinstance(meta, dict):
        return False
    art = normalize_article_number(str(meta.get("article_number") or ""))
    return art == normalize_article_number(article)


def doc_mentions_article(text: str, article: str) -> bool:
    if not article:
        return False
    blob = (text or "").lower()
    return bool(re.search(rf"(?:ст\.?|статья)\s*{re.escape(article.lower())}\b", blob))


def is_repeal_only_snippet(text: str, *, article: Optional[str] = None) -> bool:
    """Фрагмент в основном об утрате силы, без полноценного текста нормы."""
    t = (text or "").strip()
    if len(t) < 25:
        return False
    low = t.lower()
    if not any(m in low for m in _REPEAL_MARKERS):
        return False
    if len(t) >= 900:
        return False
    # признаки полноценной статьи
    if re.search(r"\n\s*1\.\s", t) or re.search(r"пункт\s+1", low):
        return False
    if article and doc_mentions_article(t, article) and len(t) >= 500:
        return False
    return True


def _infer_comparative_bankruptcy_articles(plan: LegalRetrievalPlan, question: str = "") -> List[str]:
    """
    Для сравнительных вопросов гражданин vs ЮЛ — целевые статьи порогов (metadata lookup).
    Не подставляет номера в search_queries; только structured gap-fill.
    """
    if plan.topic != "general_bankruptcy":
        return []
    blob = " ".join([question] + list(plan.facts or []) + list(plan.search_queries or [])).lower()
    has_citizen = "гражданин" in blob
    has_ul = "юрлиц" in blob or "юридическ" in blob
    if not (has_citizen and has_ul):
        return []
    comparative = any(w in blob for w in ("отлич", "различ", "сравн", "ключев"))
    creditor_ctx = "кредитор" in blob
    if not comparative and not creditor_ctx:
        return []
    arts: List[str] = []
    if has_ul:
        arts.extend(["3", "33"])
    if has_citizen:
        arts.append("213.3")
    return arts


def coverage_target_articles(plan: LegalRetrievalPlan, question: str = "") -> List[str]:
    """Явные статьи пользователя + выведенные слоты (сравнение порогов банкротства)."""
    out: List[str] = []
    seen: set[str] = set()
    for a in list(structured_lookup_articles(plan) or []) + _infer_comparative_bankruptcy_articles(
        plan, question
    ):
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def plan_coverage(
    docs: Sequence,
    plan: LegalRetrievalPlan,
    *,
    question: str = "",
    min_chars_per_article: int = 200,
) -> dict:
    """Какие целевые статьи покрыты — по metadata.article_number, не по тексту."""
    covered: List[str] = []
    missing: List[str] = []
    repeal_only: List[str] = []
    user_clause = normalize_article_number(plan.user_clause_ref or "")
    targets = coverage_target_articles(plan, question) or list(plan.required_articles or [])

    for art in targets:
        matching = [d for d in docs if doc_metadata_matches_article(d, art)]
        if user_clause and art in (plan.user_articles or []):
            matching = [
                d
                for d in matching
                if normalize_article_number(str((getattr(d, "metadata", None) or {}).get("clause_ref") or ""))
                == user_clause
            ]

        substantive = False
        only_repeal = False
        for d in matching:
            text = getattr(d, "page_content", None) or ""
            if is_repeal_only_snippet(text, article=art):
                only_repeal = True
                continue
            if len(text.strip()) >= min_chars_per_article:
                substantive = True
                break

        if not substantive and matching and plan.topic == "article_lookup" and not user_clause:
            total_chars = sum(len((getattr(d, "page_content", None) or "").strip()) for d in matching)
            substantive = len(matching) >= 2 or total_chars >= max(min_chars_per_article * 2, 400)

        if substantive:
            covered.append(art)
        elif only_repeal:
            repeal_only.append(art)
            missing.append(art)
        else:
            missing.append(art)

    return {
        "covered": covered,
        "missing": missing,
        "repeal_only": repeal_only,
    }


def structured_lookup_articles(plan: LegalRetrievalPlan) -> List[str]:
    """Статьи для norm tree / FTS / graph cluster — только явно из вопроса пользователя."""
    return list(plan.user_articles or [])


_QUERY_ARTICLE_RE = re.compile(
    r"(?:ст\.?|статья|ст\.)\s*([0-9]{1,5}(?:\.[0-9]{1,3})?)",
    re.IGNORECASE,
)


def allowed_user_article_numbers(question: str, plan: Optional[LegalRetrievalPlan] = None) -> frozenset[str]:
    """Номера статей, которые пользователь явно назвал (для фильтра search_queries)."""
    arts = set(extract_all_article_numbers(question))
    if plan:
        arts.update(plan.user_articles or [])
    return frozenset(arts)


def sanitize_planner_search_query(query: str, allowed_articles: frozenset[str]) -> Optional[str]:
    """
    Убирает фразы с «статья N», если N не назван пользователем.
    Возвращает None, если после очистки строка пустая или только номер статьи.
    """
    t = (query or "").strip()
    if not t:
        return None
    if not allowed_articles:
        mentioned = _QUERY_ARTICLE_RE.findall(t)
        if mentioned:
            return None
        return t
    cleaned = t
    for m in _QUERY_ARTICLE_RE.finditer(t):
        art = m.group(1)
        if art not in allowed_articles:
            return None
    return cleaned


def is_near_duplicate_of_question(query: str, question: str) -> bool:
    """True, если query — по сути полный вопрос пользователя (не короткая поисковая фраза)."""
    q = (question or "").strip().lower()
    t = (query or "").strip().lower()
    if not q or not t:
        return False
    if t == q:
        return True
    if len(t) > 120 and (t in q or q in t):
        return True
    if len(t) >= int(len(q) * 0.85) and t[:80] == q[:80]:
        return True
    return False


def _hybrid_query_cap() -> int:
    return max(4, min(12, int(getattr(config, "LEGAL_CORPUS_MAX_HYBRID_QUERIES", 5) or 5)))


def _legal_hybrid_phrase_from_fact(fact: str) -> str:
    """
    Пороговые facts планировщика → юридические поисковые фразы (лексика 127-ФЗ).
    Без LLM; только известные шаблоны банкротства.
    """
    t = (fact or "").lower()
    if "юрлиц" in t and any(x in t for x in ("2", "два", "миллион", "млн")):
        return (
            "признание должника банкротом принятие заявления арбитражным судом "
            "совокупность требований не менее двух миллионов рублей юридическое лицо"
        )
    if "гражданин" in t and any(x in t for x in ("500", "пятьсот", "тысяч")):
        return (
            "возбуждение производства по делу о банкротстве гражданина "
            "заявление конкурсного кредитора требования не менее пятисот тысяч рублей"
        )
    if "месяц" in t and any(x in t for x in ("3", "три", "просроч")):
        return "срок просрочки исполнения денежных обязательств три месяца банкротство"
    return (fact or "").strip()


def _fact_has_retrieval_anchor(text: str) -> bool:
    """Факт с числовым порогом/сроком — отдельный hybrid-слот (суммы, месяцы)."""
    t = (text or "").lower()
    return bool(re.search(r"(\d|миллион|млн|тысяч|рубл|месяц)", t))


def build_hybrid_queries_from_plan(plan: LegalRetrievalPlan, question: str = "") -> List[str]:
    """
    Пул запросов для norm-hybrid: search_queries + facts (отдельный проход на каждый слот).
    Пороговые facts (суммы, сроки) чередуются с search_queries в начале пула.
    """
    allowed = allowed_user_article_numbers(question, plan)
    cap = _hybrid_query_cap()

    sq_cleaned: List[str] = []
    for sq in plan.search_queries or []:
        cleaned = sanitize_planner_search_query(sq, allowed)
        if cleaned:
            sq_cleaned.append(cleaned)

    fact_cleaned: List[str] = []
    for fact in plan.facts or []:
        cleaned = sanitize_planner_search_query(fact, allowed)
        if cleaned:
            fact_cleaned.append(_legal_hybrid_phrase_from_fact(cleaned))

    critical_facts = [f for f in fact_cleaned if _fact_has_retrieval_anchor(f)]
    other_facts = [f for f in fact_cleaned if f not in critical_facts]

    candidates: List[str] = []
    for i, cf in enumerate(critical_facts):
        if i < len(sq_cleaned):
            candidates.append(sq_cleaned[i])
        candidates.append(cf)
    for sq in sq_cleaned[len(critical_facts) :]:
        candidates.append(sq)
    candidates.extend(other_facts)

    out: List[str] = []
    seen: set[str] = set()
    for raw in candidates:
        t = raw.strip()
        if not t or is_near_duplicate_of_question(t, question):
            continue
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
        if len(out) >= cap:
            break

    if out:
        return out
    return effective_search_queries(plan, question)


def effective_search_queries(plan: LegalRetrievalPlan, question: str = "") -> List[str]:
    """Короткие поисковые фразы плана; без полного текста вопроса."""
    if plan.search_queries:
        return list(plan.search_queries)
    if plan.facts:
        return _dedupe_queries(plan.facts, cap=5)
    arts = structured_lookup_articles(plan)
    if arts:
        return _dedupe_queries(
            [f"статья {a} 127-ФЗ" for a in arts],
            cap=4,
        )
    q = (question or "").strip()
    if len(q) > 160:
        return [q[:160]]
    return [q] if q else [" "]


def plan_is_sufficient(
    docs: Sequence,
    plan: LegalRetrievalPlan,
    *,
    min_total_chars: int = 400,
) -> bool:
    """
    Достаточность: для явных статей пользователя — покрытие; иначе — объём контекста.
    Номера статей из LLM-плана не участвуют (только user_articles).
    """
    if not docs:
        return False
    total = sum(len((getattr(d, "page_content", None) or "")) for d in docs)
    if total < min_total_chars:
        return False

    user_arts = structured_lookup_articles(plan)
    if not user_arts:
        return total >= min_total_chars * 2

    cov = plan_coverage(docs, plan)
    missing = cov["missing"]

    if plan.topic == "article_lookup":
        return all(art not in missing for art in user_arts)

    if len(user_arts) <= 2:
        return all(art not in missing for art in user_arts)

    covered = cov["covered"]
    need = max(1, (len(user_arts) * 2 + 2) // 3)
    return len(covered) >= need
