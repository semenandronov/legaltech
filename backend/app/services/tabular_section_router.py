"""Route tabular column queries to document section_root_ids (outline / TOC).

Production contract:
- Outline is built at ingest from LegalChunkerV2 macro sections (real headings).
- Router picks 0..N section_root_ids by exact clause, RU/EN lexical overlap, or
  column-type hints.
- Empty / weak route → full_file (no hard filter). Never invent sections.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence, Tuple

from app.config import config
from app.services.tabular_document_context import TabularFileContextPackage

RouteMethod = Literal[
    "full_file",
    "exact_clause",
    "lexical_overlap",
    "column_type_hint",
    "disabled",
]


@dataclass(frozen=True)
class SectionRoutePlan:
    section_root_ids: Tuple[str, ...]
    route_method: RouteMethod
    confidence: float
    rationale: str = ""


def tabular_section_router_enabled() -> bool:
    return bool(getattr(config, "TABULAR_SECTION_ROUTER_ENABLED", True))


def tabular_section_router_max_roots() -> int:
    return max(1, int(getattr(config, "TABULAR_SECTION_ROUTER_MAX_ROOTS", 5) or 5))


def tabular_section_router_min_confidence() -> float:
    return float(getattr(config, "TABULAR_SECTION_ROUTER_MIN_CONFIDENCE", 0.55) or 0.55)


_TOKEN_RE = re.compile(r"[\w\u0400-\u04FF]+", re.UNICODE)

# Question / column intent → words that often appear in RU/EN section titles.
_INTENT_SYNONYMS: Tuple[Tuple[re.Pattern[str], Tuple[str, ...]], ...] = (
    (
        re.compile(
            r"(?i)арендодател|арендатор|сторон\w*|landlord|tenant|party|parties|"
            r"поставщик|покупател|заказчик|исполнител|подрядчик"
        ),
        (
            "сторон",
            "предмет",
            "преамбул",
            "party",
            "parties",
            "landlord",
            "tenant",
            "definitions",
        ),
    ),
    (
        re.compile(r"(?i)номер\s+договор|дата\s+(?:договор|документ)|подписан"),
        ("предмет", "общие", "заключен", "реквизит", "преамбул"),
    ),
    (
        re.compile(
            r"(?i)предмет|объект\s+аренды|что\s+переда|имущество|товар|работ\w*|услуг"
        ),
        ("предмет", "объект", "имущество", "товар", "работ", "услуг", "subject", "scope"),
    ),
    (
        re.compile(r"(?i)арендн\w*\s+плат|плата|цена|стоимост|сумм|расч[её]т|оплат"),
        (
            "плат",
            "цена",
            "стоимост",
            "оплат",
            "расч",
            "вознагражд",
            "price",
            "payment",
            "consideration",
        ),
    ),
    (
        re.compile(r"(?i)срок|период|продолжительн|term\b|duration"),
        ("срок", "период", "действи", "term", "duration", "period"),
    ),
    (
        re.compile(r"(?i)неустойк|пен\w*|штраф|убытк|ответственност|indemnif"),
        (
            "ответственн",
            "неустойк",
            "штраф",
            "пен",
            "убытк",
            "обеспечен",
            "indemn",
            "liability",
            "damages",
        ),
    ),
    (
        re.compile(r"(?i)расторжен|отказ|прекращен|terminat|withdrawal"),
        (
            "расторжен",
            "прекращен",
            "отказ",
            "изменен",
            "terminat",
            "cancellation",
            "withdrawal",
        ),
    ),
    (
        re.compile(r"(?i)выкуп|buyout|purchase\s+option"),
        ("выкуп", "переход права", "собственн", "buyout", "purchase"),
    ),
    (
        re.compile(r"(?i)применим\w*\s+прав|подсудност|спор|governing\s+law|jurisdiction"),
        (
            "спор",
            "подсудност",
            "применим",
            "разрешен",
            "governing",
            "law",
            "jurisdiction",
            "dispute",
        ),
    ),
    (
        re.compile(r"(?i)риск|risk"),
        (
            "ответственн",
            "риск",
            "расторжен",
            "обеспечен",
            "гарант",
            "indemn",
            "liability",
            "termination",
        ),
    ),
)

_MIN_LEXICAL_SCORE = 1.5


def _tokens(text: str) -> List[str]:
    return [t.lower().replace("ё", "е") for t in _TOKEN_RE.findall(text or "") if len(t) > 1]


def _intent_boost_terms(blob: str) -> Tuple[str, ...]:
    terms: List[str] = []
    for pattern, syns in _INTENT_SYNONYMS:
        if pattern.search(blob or ""):
            terms.extend(syns)
    # Preserve order, drop dupes.
    return tuple(dict.fromkeys(terms))


def _score_section(
    *,
    title: str,
    label: str,
    number: str,
    query_tokens: Sequence[str],
    lexical_terms: Sequence[str],
    intent_terms: Sequence[str],
) -> float:
    blob = f"{number} {title} {label}".lower().replace("ё", "е")
    if not blob.strip():
        return 0.0
    score = 0.0
    for term in lexical_terms:
        t = term.lower().strip().replace("ё", "е")
        if len(t) < 2:
            continue
        if t in blob:
            score += 2.0
    for term in intent_terms:
        t = term.lower().replace("ё", "е")
        if len(t) < 3:
            continue
        if t in blob:
            score += 2.5
    for tok in query_tokens[:20]:
        if len(tok) < 3:
            continue
        if tok in blob:
            score += 0.6
    return score


def _match_exact_clause_roots(
    exact_query: str,
    outline: TabularFileContextPackage,
) -> Tuple[str, ...]:
    eq = (exact_query or "").strip()
    if not eq:
        return ()
    hits: List[str] = []
    eq_l = eq.lower()
    for entry in outline.outline:
        num = (entry.section_number or "").strip()
        title = (entry.section_title or "").strip()
        label = (entry.section_label or "").strip()
        if not num and not title:
            continue
        if eq == num or eq_l == title.lower() or title.lower().startswith(eq_l):
            hits.append(entry.section_root_id)
        elif num and (num == eq or num.startswith(eq) or eq.startswith(num)):
            hits.append(entry.section_root_id)
        elif label and eq_l in label.lower():
            hits.append(entry.section_root_id)
    return tuple(dict.fromkeys(hits))


def route_column_to_sections(
    *,
    file_context: Optional[TabularFileContextPackage],
    semantic_query: str,
    lexical_terms: Sequence[str],
    exact_query: str,
    column_type: str,
    column_label: str = "",
) -> SectionRoutePlan:
    """
    Pick outline sections for a column question.

    Returns empty section_root_ids with method full_file/disabled when routing
    must not hard-filter retrieval (no outline, weak match, or router off).
    """
    if not tabular_section_router_enabled():
        return SectionRoutePlan((), "disabled", 0.0, "router_disabled")
    if file_context is None or not file_context.outline:
        return SectionRoutePlan((), "full_file", 0.0, "empty_outline_full_file")

    max_roots = tabular_section_router_max_roots()
    exact_hits = _match_exact_clause_roots(exact_query, file_context)
    if exact_hits:
        return SectionRoutePlan(
            exact_hits[:max_roots],
            "exact_clause",
            0.95,
            f"exact_clause:{exact_query}",
        )

    intent_blob = f"{column_label or ''} {semantic_query or ''}".strip()
    intent_terms = _intent_boost_terms(intent_blob)
    query_tokens = _tokens(f"{semantic_query} {column_label}")
    scored: List[Tuple[float, str, str]] = []
    for entry in file_context.outline:
        sid = entry.section_root_id
        title = entry.section_title or entry.section_number or sid
        label = entry.section_label or title
        sc = _score_section(
            title=title,
            label=label,
            number=entry.section_number or "",
            query_tokens=query_tokens,
            lexical_terms=lexical_terms,
            intent_terms=intent_terms,
        )
        if sc >= _MIN_LEXICAL_SCORE:
            scored.append((sc, sid, title))

    scored.sort(key=lambda x: (-x[0], x[1]))
    roots = [sid for _, sid, _ in scored[:max_roots]]
    method: RouteMethod = "lexical_overlap"

    # Dates / yes-no often live in preamble + early body.
    if column_type in ("date", "yes_no") and file_context.outline:
        header_roots = [file_context.outline[0].section_root_id]
        if len(file_context.outline) > 1:
            header_roots.append(file_context.outline[1].section_root_id)
        roots = list(dict.fromkeys([*header_roots, *roots]))[:max_roots]
        if not scored:
            method = "column_type_hint"

    if not roots:
        return SectionRoutePlan((), "full_file", 0.2, "no_section_match_full_file")

    top_score = scored[0][0] if scored else 0.5
    conf = min(0.92, 0.35 + 0.08 * top_score)
    if method == "column_type_hint":
        conf = min(conf, 0.5)

    min_conf = tabular_section_router_min_confidence()
    if conf < min_conf and method != "exact_clause":
        return SectionRoutePlan(
            (),
            "full_file",
            conf,
            f"weak_route_score={top_score:.2f}_full_file",
        )

    titles = ", ".join(t for _, _, t in scored[:3])
    return SectionRoutePlan(
        tuple(roots),
        method,
        conf,
        f"top_score={top_score:.2f}; hits={titles}",
    )
