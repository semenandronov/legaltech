"""
Phase 1 — structural referential turn classification (0 ms, deterministic).

Single classifier for Turn Context Contract. Separates:
- memory_synthesis: answer already in prior assistant text
- citation_expand: user wants source/quote location
- scoped_deep_read: user points at entity in prior answer, needs scoped RAG

Not a keyword patch list — each class maps to a distinct pipeline path.
"""
from __future__ import annotations

import re
from typing import Literal

from app.services.chat.reference_resolver import is_deictic_reference
from app.services.chat.standalone_query_resolver import needs_standalone_resolution

ReferentialKind = Literal[
    "none",
    "memory_synthesis",
    "scoped_deep_read",
    "citation_expand",
]

SHORT_REFERENTIAL_MAX_WORDS = 24
_SHORT_REFERENTIAL_MAX_CHARS = 280

_MEMORY_SYNTHESIS_RE = re.compile(
    r"(?:"
    r"\bключев\w*\s+вывод\w*"
    r"|\bглавн\w*\s+вывод\w*"
    r"|\bосновн\w*\s+вывод\w*"
    r"|\bитог\w*"
    r"|\bрезюме\b"
    r"|\bкратко\s+повтори"
    r"|\bперескаж\w*"
    r"|\bсуммир\w*"
    r"|\bвывод\w*\s*\??\s*$"
    r")",
    re.IGNORECASE,
)

_CITATION_EXPAND_RE = re.compile(
    r"(?:"
    r"\bгде\s+(?:об\s+)?(?:этом|этом\s+написан\w*)"
    r"|\bпокаж\w*\s+(?:этот|эту|это)\s+(?:абзац|фрагмент|цитат\w*|источник\w*)"
    r"|\bоткуда\s+(?:это|данн\w*|ты\s+(?:взял|взяла|привел))"
    r"|\bисточник\w*\s+(?:этого|этой|этих)"
    r"|\bв\s+каком\s+(?:документ\w*|файл\w*|мест\w*)"
    r")",
    re.IGNORECASE,
)

# Ordinal / entity pointer without full noun phrase — requires prior-turn context.
_ENTITY_POINTER_RE = re.compile(
    r"\b(?:"
    r"пункт\w*|п\.?\s*\d+"
    r"|сумм\w*"
    r"|риск\w*"
    r"|абзац\w*"
    r"|стать\w*"
    r"|услови\w*"
    r")\b",
    re.IGNORECASE,
)


def is_short_referential_question(question: str) -> bool:
    q = (question or "").strip()
    if not q or len(q) > _SHORT_REFERENTIAL_MAX_CHARS:
        return False
    return len(q.split()) <= SHORT_REFERENTIAL_MAX_WORDS


def is_memory_synthesis_question(question: str) -> bool:
    return bool(_MEMORY_SYNTHESIS_RE.search((question or "").strip()))


def is_citation_expand_question(question: str) -> bool:
    return bool(_CITATION_EXPAND_RE.search((question or "").strip()))


def needs_prior_turn_resolution(question: str) -> bool:
    """Question contains unresolved pointer to prior answer (deictic or ordinal)."""
    q = (question or "").strip()
    if not q:
        return False
    if needs_standalone_resolution(q):
        return True
    if is_deictic_reference(q):
        return True
    return bool(_ENTITY_POINTER_RE.search(q))


def classify_referential_kind(question: str, *, has_prior: bool) -> ReferentialKind:
    """
    Structural referential kind for one user turn.

    Requires a prior assistant turn with content; long or explicit new-topic
    questions return ``none`` and follow the normal retrieval path.
    """
    q = (question or "").strip()
    if not q or not has_prior or not is_short_referential_question(q):
        return "none"

    if is_memory_synthesis_question(q):
        return "memory_synthesis"
    if is_citation_expand_question(q):
        return "citation_expand"
    if needs_prior_turn_resolution(q):
        return "scoped_deep_read"
    return "none"
