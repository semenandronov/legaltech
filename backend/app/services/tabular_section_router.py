"""Route tabular column queries to document section_root_ids."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence, Tuple

from app.config import config
from app.services.tabular_document_context import TabularFileContextPackage

RouteMethod = Literal["full_file", "exact_clause", "lexical_overlap", "column_type_hint", "disabled"]


@dataclass(frozen=True)
class SectionRoutePlan:
    section_root_ids: Tuple[str, ...]
    route_method: RouteMethod
    confidence: float
    rationale: str = ""


def tabular_section_router_enabled() -> bool:
    return bool(getattr(config, "TABULAR_SECTION_ROUTER_ENABLED", False))


def tabular_section_router_max_roots() -> int:
    return max(1, int(getattr(config, "TABULAR_SECTION_ROUTER_MAX_ROOTS", 5) or 5))


_TOKEN_RE = re.compile(r"[\w\u0400-\u04FF]+", re.UNICODE)
_EN_SECTION_KW = re.compile(
    r"(?i)\b(?:article|section|schedule|exhibit|definitions?|representations?|"
    r"covenants?|termination|indemnif|conditions?\s+to\s+closing)\b"
)


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1]


def _score_section(
    *,
    title: str,
    label: str,
    query_tokens: Sequence[str],
    lexical_terms: Sequence[str],
) -> float:
    blob = f"{title} {label}".lower()
    if not blob.strip():
        return 0.0
    score = 0.0
    for term in lexical_terms:
        t = term.lower().strip()
        if len(t) < 2:
            continue
        if t in blob:
            score += 2.0
    for tok in query_tokens[:16]:
        if tok in blob:
            score += 0.5
    if _EN_SECTION_KW.search(blob):
        score += 0.25
    return score


def _match_exact_clause_roots(
    exact_query: str,
    outline: TabularFileContextPackage,
) -> Tuple[str, ...]:
    eq = (exact_query or "").strip()
    if not eq:
        return ()
    hits: List[str] = []
    for entry in outline.outline:
        num = entry.section_number or ""
        title = entry.section_title or ""
        if eq == num or eq in title or title.startswith(eq):
            hits.append(entry.section_root_id)
        elif num and num.startswith(eq):
            hits.append(entry.section_root_id)
    return tuple(dict.fromkeys(hits))


def route_column_to_sections(
    *,
    file_context: Optional[TabularFileContextPackage],
    semantic_query: str,
    lexical_terms: Sequence[str],
    exact_query: str,
    column_type: str,
) -> SectionRoutePlan:
    if not tabular_section_router_enabled() or file_context is None or not file_context.outline:
        return SectionRoutePlan((), "disabled", 0.0, "router_disabled_or_empty_outline")

    max_roots = tabular_section_router_max_roots()
    exact_hits = _match_exact_clause_roots(exact_query, file_context)
    if exact_hits:
        return SectionRoutePlan(
            exact_hits[:max_roots],
            "exact_clause",
            0.95,
            f"exact_clause:{exact_query}",
        )

    query_tokens = _tokens(semantic_query)
    scored: List[Tuple[float, str]] = []
    for sid, title, label in file_context.outline_titles_for_router():
        sc = _score_section(
            title=title,
            label=label,
            query_tokens=query_tokens,
            lexical_terms=lexical_terms,
        )
        if sc > 0:
            scored.append((sc, sid))

    scored.sort(key=lambda x: (-x[0], x[1]))
    roots = [sid for _, sid in scored[:max_roots]]

    if column_type in ("date", "yes_no") and file_context.outline:
        header_roots = [file_context.outline[0].section_root_id]
        if len(file_context.outline) > 1:
            header_roots.append(file_context.outline[1].section_root_id)
        roots = list(dict.fromkeys([*header_roots, *roots]))[:max_roots]

    if not roots:
        return SectionRoutePlan((), "full_file", 0.2, "no_section_match_full_file")

    top_score = scored[0][0] if scored else 0.5
    conf = min(0.92, 0.35 + 0.1 * top_score)
    return SectionRoutePlan(
        tuple(roots),
        "lexical_overlap",
        conf,
        f"top_score={top_score:.2f}",
    )
