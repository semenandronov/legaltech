from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from app.services.legal_instruments import INSTRUMENTS

# Сколько разных поисковых строк отдавать в multi-query retrieval (дедуп по lower).
MAX_ROUTE_QUERIES = 6

_RELATIVE_MARKERS: Tuple[str, ...] = (
    "брат",
    "сестра",
    "родствен",
    "родств",
    "двоюродн",
    "тесть",
    "теща",
    "свёкр",
    "свекр",
    "свекров",
    "зять",
    "невестк",
    "шурин",
    "племянник",
    "внук",
    "внуч",
    "дедуш",
    "бабуш",
    "сын",
    "дочь",
    "мать",
    "отец",
    "мама",
    "папа",
    "супруг",
    "аффилир",
)

_SUSPICIOUS_DEAL_MARKERS: Tuple[str, ...] = (
    "продал",
    "продала",
    "продаж",
    "реализ",
    "отчужд",
    "участок",
    "земельн",
    "автомобил",
    "машин",
    "транспорт",
    "недвижим",
    "имуществ",
    "вывод актив",
    "занижен",
    "дешев",
    "бесценок",
    "дарен",
    "безвозмездн",
)

_PREFERENTIAL_MARKERS: Tuple[str, ...] = (
    "предпочтит",
    "предпочтен",
    "отдельн кредитор",
    "61.3",
)


def _has_any(haystack_lower: str, needles: Sequence[str]) -> bool:
    return any(n in haystack_lower for n in needles)


def _dedupe_queries_preserve_order(strings: Iterable[str], *, cap: int) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for raw in strings:
        t = (raw or "").strip()
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
        if len(out) >= cap:
            break
    return out


@dataclass(frozen=True)
class LegalCorpusRoute:
    instrument_ids: List[str]
    queries: List[str]
    rationale: str


# Статьи, которые в типичном юр. вопросе без кодаекса отсылают к 127‑ФЗ (банкротство).
_FZ127_ARTICLE_ROOTS: Tuple[str, ...] = (
    "10",
    "19",
    "20",
    "61",
    "71",
    "213",
)


def extract_article_number(query: str) -> Optional[str]:
    """Номер статьи из вопроса (ст. 61.2 → 61.2)."""
    q = (query or "").lower()
    m = re.search(r"(?:ст\.?|статья)\s*([0-9]{1,5}(?:\.[0-9]{1,3})?)", q)
    if m:
        return m.group(1)
    if re.fullmatch(r"\s*[0-9]{1,5}(?:\.[0-9]{1,3})?\s*", q):
        return q.strip()
    return None


def article_suggests_fz127(article: Optional[str]) -> bool:
    if not article:
        return False
    root = article.split(".")[0]
    return root in _FZ127_ARTICLE_ROOTS


def detect_instruments_from_question(question: str) -> List[str]:
    """Явные упоминания актов в тексте вопроса (aliases из реестра)."""
    ql = (question or "").lower()
    found: List[str] = []
    for iid, inst in INSTRUMENTS.items():
        if iid in ("other",):
            continue
        needles = [inst.short_name.lower(), iid.replace("-", " ")]
        needles.extend(a.lower() for a in (inst.aliases or ()))
        if any(n and n in ql for n in needles):
            if iid not in found:
                found.append(iid)
    return found


def resolve_legal_corpus_route(
    question: str,
    *,
    legal_research: bool = False,
    task_type: Optional[str] = None,
) -> LegalCorpusRoute:
    """
    Маршрут с учётом контекста чата: явные акты в вопросе, статья без кодаекса + legal research.
    """
    base = route_legal_corpus_query(question)
    ql = (question or "").lower()
    article = extract_article_number(question)

    ids: List[str] = []
    rationale_parts: List[str] = []
    if base.instrument_ids and base.instrument_ids != ["unknown"]:
        ids.extend(base.instrument_ids)
        rationale_parts.append(base.rationale)

    for iid in detect_instruments_from_question(question):
        if iid not in ids:
            ids.append(iid)
            rationale_parts.append(f"явный акт в вопросе → {iid}")

    tt = (task_type or "").strip().lower()
    bankruptcy_task = tt in ("legal_research", "research", "bankruptcy", "insolvency")

    if not ids or ids == ["unknown"]:
        ids = [x for x in ids if x != "unknown"]
        if article and article_suggests_fz127(article) and (legal_research or bankruptcy_task):
            ids = ["fz-127", "plenum-63"]
            rationale_parts.append(
                f"статья {article} без кодаекса + контекст legal research → 127‑ФЗ + Пленум №63"
            )

    if not ids:
        ids = ["unknown"]
        if not rationale_parts:
            rationale_parts.append(base.rationale or "нет детерминированных маркеров → unknown")

    queries = list(base.queries)
    if article and "fz-127" in ids:
        art_q = f"статья {article} 127-ФЗ".strip()
        if art_q.lower() not in {q.lower() for q in queries}:
            queries.insert(1, art_q)

    queries = _dedupe_queries_preserve_order(queries, cap=MAX_ROUTE_QUERIES)
    return LegalCorpusRoute(
        instrument_ids=ids,
        queries=queries,
        rationale="; ".join(rationale_parts) if rationale_parts else base.rationale,
    )


def route_legal_corpus_query(question: str) -> LegalCorpusRoute:
    """
    MVP router for СПРАВОЧНИК mode.

    Design goals:
    - deterministic and debuggable (no LLM call)
    - returns instrument_ids for metadata filtering + a small set of search queries
    - implements "context pair": fz-127 => also search plenum-63 by default
    - query expansion: бытовые маркеры → юридические формулировки для hybrid + rerank
    """
    q = (question or "").strip()
    ql = q.lower()

    # hard markers for bankruptcy domain
    bankruptcy_markers = (
        "банкрот",
        "несостоятельн",
        "конкурсн",
        "реестр требований",
        "кредитор",
        "оспарив",
        "оспорить",
        "подозрительн",
        "неравноцен",
        "субсидиарн",
        "сделк",
        "недействительн",
        "родственник",
        "аффилир",
        "61.",
        "127",
        "фз-127",
        "127-фз",
        "должник",
        "конкурсн масса",
        "финансовый управляющ",
    )

    instrument_ids: List[str] = []
    rationale_parts: List[str] = []

    has_bankruptcy = any(m in ql for m in bankruptcy_markers)
    # «статья 61» / «ст. 61.2» без слова «банкротство» — типичный вопрос по 127‑ФЗ
    if not has_bankruptcy and re.search(r"(?:ст\.?|статья)\s*6[0-9]", ql):
        has_bankruptcy = True
        rationale_parts.append("упоминание статьи 6x → предполагаем 127‑ФЗ")

    # "родственник + сделка" без явного слова «банкротство» — всё равно банкротный контекст
    has_relative_deal = (
        not has_bankruptcy
        and _has_any(ql, _RELATIVE_MARKERS)
        and _has_any(ql, _SUSPICIOUS_DEAL_MARKERS)
    )
    if has_relative_deal:
        has_bankruptcy = True
        rationale_parts.append("комбинация родственник+сделка → предполагаем банкротный контекст")

    if has_bankruptcy:
        instrument_ids.append("fz-127")
        rationale_parts.append("обнаружены маркеры банкротства/оспаривания → fz-127")

        # context pair: add key practice doc if present in corpus
        instrument_ids.append("plenum-63")
        rationale_parts.append("контекстная пара для оспаривания сделок → plenum-63")

    # fallback: if no clear routing, keep unfiltered (handled by caller)
    if not instrument_ids:
        instrument_ids = ["unknown"]
        rationale_parts.append("нет детерминированных маркеров → unknown (без фильтра)")

    # --- queries: original + optional article squeeze + семантическое расширение ---
    query_candidates: List[str] = [q]
    if "ст." in ql or "статья" in ql:
        query_candidates.append(q.replace("статья", "ст."))

    expansion_notes: List[str] = []
    if has_bankruptcy:
        if _has_any(ql, _RELATIVE_MARKERS):
            query_candidates.append(
                "статья 19 127-ФЗ заинтересованное лицо должника родственники оспаривание сделки"
            )
            expansion_notes.append("родственники/аффилиация → ст.19")
        if _has_any(ql, _SUSPICIOUS_DEAL_MARKERS) or (
            "оспарив" in ql and ("сделк" in ql or "должник" in ql)
        ):
            query_candidates.append(
                "статья 61.2 127-ФЗ подозрительная сделка срок один год три года неравноценность"
            )
            expansion_notes.append("оспаривание/отчуждение → ст.61.2")
            query_candidates.append(
                "статья 61.1 127-ФЗ оспаривание сделки должника основания"
            )
            query_candidates.append(
                "статья 61.3 127-ФЗ предпочтительная сделка кредитор"
            )
        if _has_any(ql, _PREFERENTIAL_MARKERS):
            query_candidates.append(
                "статья 61.3 127-ФЗ предпочтительная сделка кредитор шесть месяцев"
            )
            expansion_notes.append("предпочтение кредитору → ст.61.3")
        if "субсидиар" in ql:
            query_candidates.append(
                "статья 10.4 127-ФЗ субсидиарная ответственность контролирующее должника лицо"
            )
            expansion_notes.append("субсидиарная → ст.10.4")

        # общий «широкий» запрос — только если ещё есть слоты
        query_candidates.append(
            "заинтересованное лицо должника оспаривание сделки "
            "недействительность сделки несостоятельность банкротство"
        )

    queries = _dedupe_queries_preserve_order(query_candidates, cap=MAX_ROUTE_QUERIES)
    if expansion_notes:
        rationale_parts.append("расширение запросов: " + "; ".join(expansion_notes))

    return LegalCorpusRoute(
        instrument_ids=instrument_ids,
        queries=queries,
        rationale="; ".join(rationale_parts),
    )
