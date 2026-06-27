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
    if topic == "challenge_transactions":
        return ["61.1", "61.2", "61.3"]
    if topic == "limitation_challenge":
        return ["61.1", "61.2", "61.3", "61.9"]
    return []


def _queries_for_topic(topic: LegalRetrievalTopic, ql: str) -> List[str]:
    if topic == "challenge_transactions":
        return [
            "статья 61.1 127-ФЗ оспаривание сделки должника основания",
            "статья 61.2 127-ФЗ подозрительная сделка срок один год три года",
            "статья 61.3 127-ФЗ предпочтительная сделка шесть месяцев кредитор",
            "пленум 63 оспаривание сделки должника срок",
        ]
    if topic == "limitation_challenge":
        return [
            "статья 61.9 127-ФЗ исковая давность оспаривание сделки",
            "статья 61.2 127-ФЗ подозрительная сделка период один год три года",
            "срок исковой давности оспаривание сделки должника арбитражный управляющий",
        ]
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

    queries: List[str] = [q]
    queries.extend(route_queries or [])
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


def plan_coverage(
    docs: Sequence,
    plan: LegalRetrievalPlan,
    *,
    min_chars_per_article: int = 200,
) -> dict:
    """Какие целевые статьи покрыты — по metadata.article_number, не по тексту."""
    covered: List[str] = []
    missing: List[str] = []
    repeal_only: List[str] = []
    user_clause = normalize_article_number(plan.user_clause_ref or "")

    for art in plan.required_articles:
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


def plan_is_sufficient(
    docs: Sequence,
    plan: LegalRetrievalPlan,
    *,
    min_total_chars: int = 400,
) -> bool:
    """
    Достаточность только по плану: required_articles и объём контекста.
    Не привязываемся к фиксированным ст. 61.x при произвольном topic/required.
    """
    if not docs:
        return False
    total = sum(len((getattr(d, "page_content", None) or "")) for d in docs)
    if total < min_total_chars:
        return False

    if not plan.required_articles:
        return total >= min_total_chars * 2

    cov = plan_coverage(docs, plan)
    missing = cov["missing"]
    covered = cov["covered"]

    # article_lookup: все статьи, явно запрошенные пользователем
    if plan.topic == "article_lookup" and plan.user_articles:
        for art in plan.user_articles:
            if art in missing:
                return False
        return True

    n_req = len(plan.required_articles)
    if n_req <= 2:
        return len(missing) == 0
    # 3+ статей в плане: сильное большинство должно быть покрыто содержательно
    need = max(1, (n_req * 2 + 2) // 3)
    return len(covered) >= need
