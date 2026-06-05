"""
Case card metadata — deterministic answers from Case row (no RAG / LangGraph).

Scalar properties: document count, status, title, creation date, case number.
Used by orchestrator before session replay and LangGraph.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.case import Case

# --- intent: exclude content/overview questions (not card scalars) ---

_OVERVIEW_CONTENT_RE = re.compile(
    r"\b(?:"
    r"о\s+ч[её]м\s+(?:документ|файл)|"
    r"содержани\w+|"
    r"кратк\w+\s+(?:содержани\w+|описани\w+)|"
    r"обзор\s+(?:документ|материал)|"
    r"что\s+в\s+(?:документ|файл)|"
    r"перескаж|"
    r"суммариз"
    r")\b",
    re.IGNORECASE,
)

_QTY_WORD_RE = re.compile(
    r"\b(?:сколько|количеств\w*|число|сколько\s+всего)\b",
    re.IGNORECASE,
)
_DOC_REF_RE = re.compile(
    r"\b(?:документ\w*|файл\w*)\b",
    re.IGNORECASE,
)
_CASE_SCOPE_RE = re.compile(
    r"(?:"
    r"в\s+дел\w*|"
    r"\bдел\w*\b|"
    r"загружен\w*|"
    r"загруж\w*|"
    r"прикреплен\w*|"
    r"материал\w*\s+дел\w*"
    r")",
    re.IGNORECASE,
)

_CASE_NUMBER_RE = re.compile(
    r"\b(?:номер\s+дела|№\s*дела|id\s*дела|ид\s*дела|идентификатор\s+дела)\b",
    re.IGNORECASE,
)
_CASE_DATE_RE = re.compile(
    r"\b(?:дата\s+дела|когда\s+создано\s+дело|дата\s+создания\s+дела)\b",
    re.IGNORECASE,
)
_CASE_STATUS_RE = re.compile(
    r"\b(?:статус\s+дела|в\s+каком\s+статусе\s+дело)\b",
    re.IGNORECASE,
)
_CASE_TITLE_RE = re.compile(
    r"\b(?:названи\w*\s+дела|как\s+называ\w*\s+дело|заголов\w*\s+дела)\b",
    re.IGNORECASE,
)

# Legacy exact phrasing (kept for regression)
_CASE_DOCS_COUNT_LEGACY_RE = re.compile(
    r"\b(?:сколько\s+документ\w*\s+в\s+деле|количеств\w*\s+документ\w*\s+в\s+деле|число\s+документ\w*\s+в\s+деле)\b",
    re.IGNORECASE,
)

_TYPO_NORMALIZERS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"л[кk]умент", re.IGNORECASE), "документ"),
    (re.compile(r"дokument", re.IGNORECASE), "документ"),
    (re.compile(r"фaйл", re.IGNORECASE), "файл"),
]


class CaseMetadataKind(str, Enum):
    DOCS_COUNT = "docs_count"
    STATUS = "status"
    TITLE = "title"
    CREATED_AT = "created_at"
    CASE_NUMBER = "case_number"


@dataclass(frozen=True)
class CaseMetadataReply:
    content: str
    citation: Dict[str, Any]
    kind: CaseMetadataKind


def normalize_question_for_metadata(question: str) -> str:
    q = " ".join((question or "").strip().lower().split())
    for pattern, repl in _TYPO_NORMALIZERS:
        q = pattern.sub(repl, q)
    return q


def is_case_metadata_question(question: str) -> bool:
    """True when the user asks for a scalar field from the case card (not document content)."""
    return classify_case_metadata_intent(question) is not None


def classify_case_metadata_intent(question: str) -> Optional[CaseMetadataKind]:
    q = normalize_question_for_metadata(question)
    if not q or len(q) > 220:
        return None
    if _OVERVIEW_CONTENT_RE.search(q):
        return None

    if _CASE_NUMBER_RE.search(q):
        return CaseMetadataKind.CASE_NUMBER
    if _CASE_DATE_RE.search(q):
        return CaseMetadataKind.CREATED_AT
    if _CASE_STATUS_RE.search(q):
        return CaseMetadataKind.STATUS
    if _is_docs_count_intent(q):
        return CaseMetadataKind.DOCS_COUNT
    if _CASE_TITLE_RE.search(q):
        return CaseMetadataKind.TITLE
    return None


def _is_docs_count_intent(q: str) -> bool:
    if _CASE_DOCS_COUNT_LEGACY_RE.search(q):
        return True
    return bool(
        _QTY_WORD_RE.search(q)
        and _DOC_REF_RE.search(q)
        and _CASE_SCOPE_RE.search(q)
    )


def build_case_metadata_citation(case_id: str, quote: str) -> Dict[str, Any]:
    return {
        "source_id": str(case_id),
        "file_name": "Карточка дела",
        "quote": quote,
        "source_type": "document",
    }


def _resolve_case_number(case_id: str, case: Case) -> str:
    meta = case.case_metadata if isinstance(case.case_metadata, dict) else {}
    for key in ("case_number", "number", "matter_number", "court_case_number"):
        raw = meta.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return str(case.id)


def resolve_case_metadata_answer(
    db: Session,
    *,
    case_id: str,
    question: str,
) -> Optional[CaseMetadataReply]:
    kind = classify_case_metadata_intent(question)
    if kind is None:
        return None

    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        return None

    if kind is CaseMetadataKind.CASE_NUMBER:
        number = _resolve_case_number(case_id, case)
        quote = f"ID/номер дела: {number}"
        return CaseMetadataReply(
            content=f"Номер дела: {number}.",
            citation=build_case_metadata_citation(case_id, quote),
            kind=kind,
        )

    if kind is CaseMetadataKind.CREATED_AT:
        created = case.created_at.isoformat() if case.created_at else "не указана"
        return CaseMetadataReply(
            content=f"Дата создания дела: {created}.",
            citation=build_case_metadata_citation(case_id, f"created_at: {created}"),
            kind=kind,
        )

    if kind is CaseMetadataKind.STATUS:
        status = (case.status or "").strip() or "не указан"
        return CaseMetadataReply(
            content=f"Статус дела: {status}.",
            citation=build_case_metadata_citation(case_id, f"status: {status}"),
            kind=kind,
        )

    if kind is CaseMetadataKind.DOCS_COUNT:
        docs_count = int(case.num_documents or 0)
        word = _docs_count_word(docs_count)
        return CaseMetadataReply(
            content=f"В дело загружено {docs_count} {word}.",
            citation=build_case_metadata_citation(case_id, f"num_documents: {docs_count}"),
            kind=kind,
        )

    if kind is CaseMetadataKind.TITLE:
        title = (case.title or "").strip() or "не указано"
        return CaseMetadataReply(
            content=f"Название дела: {title}.",
            citation=build_case_metadata_citation(case_id, f"title: {title}"),
            kind=kind,
        )

    return None


def _docs_count_word(n: int) -> str:
    n_abs = abs(n) % 100
    n1 = n_abs % 10
    if 11 <= n_abs <= 19:
        return "документов"
    if n1 == 1:
        return "документ"
    if 2 <= n1 <= 4:
        return "документа"
    return "документов"
