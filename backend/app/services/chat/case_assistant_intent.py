"""
Case assistant intent — single classification layer for policy routing.

Maps structural query features + case scope (attached files, corpus size) to:
- task_type / depth_tier (retrieval & policy family)
- response_shape (generation packaging)
- primary_intent (observability, execution tier hints)

Avoid ad-hoc keyword patches in graph nodes; extend this module for new product modes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional, Tuple

PrimaryIntentLabel = Literal[
    "empty",
    "drafting",
    "too_short",
    "case_metadata",
    "needs_clarification",
    "contradiction",
    "cross_doc_analysis",
    "legal_analysis",
    "case_corpus_overview",
    "drill_down",
    "narrow_fact",
    "standard_case_qa",
]

TaskTypeLabel = Literal[
    "fact_lookup",
    "single_doc_extraction",
    "multi_doc_synthesis",
    "legal_reasoning",
    "contradiction_check",
    "drafting",
    "clarification",
]

DepthTierLabel = Literal["fast", "deep"]
ResponseShapeLabel = Literal["fact", "executive_summary", "memorandum", "analysis"]

_OVERVIEW_DOC_RE = re.compile(
    r"(?:"
    r"о\s*ч[её]м\s+(?:все\s+)?(?:документ|файл)"
    r"|что\s+(?:за|это\s+за)\s+(?:документ|файл)"
    r"|(?:кратко|коротко)\s+(?:о|про)\s+(?:документ|файл)"
    r"|(?:содержан|резюме|сводк|опиши|перечисли|список)\w*\s+(?:документ|файл)"
    r")",
    re.IGNORECASE,
)

_PLURAL_DOCS_RE = re.compile(
    r"(?:документы|документов|файлы|файлов|все\s+документ|по\s+всем\s+документ)",
    re.IGNORECASE,
)

_DRILL_DOWN_RE = re.compile(
    r"(?:"
    r"подробн\w*"
    r"|распиш\w*"
    r"|разверн\w*"
    r"|детальн\w*"
    r"|углуб\w*"
    r"|разбер\w*"
    r"|раскрой"
    r"|поясни"
    r")",
    re.IGNORECASE,
)

_REFERENTIAL_FOLLOWUP_RE = re.compile(
    r"(?:\bтам\b|\bэтом\b|\bэтого\b|\bвыше\b|\bранее\b|\bподробнее\b|\bещё\b|\bеще\b|\bэтом\s+договор)",
    re.IGNORECASE,
)

_NAMED_SINGLE_DOC_RE = re.compile(
    r"о\s+ч[её]м\s+(?:договор|контракт|иск(?:овое)?|заявлен\w*|протокол|акт|письм\w*|решени\w*|определени\w*)",
    re.IGNORECASE,
)

_DATE_IN_QUESTION_RE = re.compile(r"\d{2}[./]\d{2}[./]\d{2,4}")

_FACT_POINT_RE = re.compile(
    r"(?:"
    r"какая\s+сумм"
    r"|какая\s+дат"
    r"|какой\s+срок"
    r"|какой\s+пункт"
    r"|номер\s+дел"
    r"|сколько"
    r"|какой\s+инн"
    r"|какая\s+сторон"
    r"|кто\s+"
    r"|когда\s+"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryFeatures:
    """Structural features — no LLM, derived once per turn."""

    question: str
    question_lower: str
    char_len: int
    word_count: int
    attached_files_count: int
    corpus_size: int
    effective_doc_scope: int
    draft_mode: bool
    legal_research: bool
    deep_think: bool


@dataclass(frozen=True)
class CaseAssistantIntent:
    """Resolved product intent for one user turn."""

    primary: PrimaryIntentLabel
    task_type: TaskTypeLabel
    depth_tier: DepthTierLabel
    response_shape: ResponseShapeLabel
    clarification_needed: bool
    reason: str
    confidence: float


def _effective_doc_scope(attached_files_count: int, corpus_size: int) -> int:
    attached = max(0, int(attached_files_count or 0))
    corpus = max(0, int(corpus_size or 0))
    return max(attached, corpus)


def extract_query_features(
    *,
    question: str,
    attached_files_count: int = 0,
    corpus_size: int = 0,
    draft_mode: bool = False,
    legal_research: bool = False,
    deep_think: bool = False,
) -> QueryFeatures:
    q = (question or "").strip()
    ql = q.lower()
    words = ql.split()
    return QueryFeatures(
        question=q,
        question_lower=ql,
        char_len=len(q),
        word_count=len(words),
        attached_files_count=max(0, int(attached_files_count or 0)),
        corpus_size=max(0, int(corpus_size or 0)),
        effective_doc_scope=_effective_doc_scope(attached_files_count, corpus_size),
        draft_mode=bool(draft_mode),
        legal_research=bool(legal_research),
        deep_think=bool(deep_think),
    )


def _has_overview_semantics(f: QueryFeatures) -> bool:
    if not f.question_lower:
        return False
    if _OVERVIEW_DOC_RE.search(f.question):
        return True
    overview_phrases = (
        "о чем документ",
        "о чём документ",
        "о чем файл",
        "что в документ",
        "что в файлах",
        "про что документ",
        "содержание документ",
        "кратко о документ",
        "резюме документ",
        "опиши документ",
        "перечисли документ",
        "список документ",
    )
    return any(p in f.question_lower for p in overview_phrases)


def _has_plural_doc_scope(f: QueryFeatures) -> bool:
    return bool(_PLURAL_DOCS_RE.search(f.question_lower))


def _has_drill_down_semantics(f: QueryFeatures) -> bool:
    if _DRILL_DOWN_RE.search(f.question_lower):
        return True
    if _REFERENTIAL_FOLLOWUP_RE.search(f.question_lower):
        return True
    return False


def _has_single_named_doc_question(f: QueryFeatures) -> bool:
    if _has_plural_doc_scope(f):
        return False
    if _NAMED_SINGLE_DOC_RE.search(f.question):
        return True
    if _DATE_IN_QUESTION_RE.search(f.question):
        doc_hints = ("договор", "контракт", "иск", "заявлен", "акт", "протокол", "решени")
        if any(h in f.question_lower for h in doc_hints):
            return True
    return False


def _has_narrow_fact_semantics(f: QueryFeatures) -> bool:
    if _FACT_POINT_RE.search(f.question_lower):
        return True
    if f.word_count <= 8 and f.char_len <= 80 and not _has_drill_down_semantics(f):
        return True
    return False


def _has_clarification_request(f: QueryFeatures) -> bool:
    markers = (
        "уточни формулировку",
        "не понял",
        "что именно",
        "по какому документу",
        "по какому периоду",
        "что сравнить",
        "какому делу",
        "без контекста",
    )
    return any(m in f.question_lower for m in markers)


def _has_synthesis_semantics(f: QueryFeatures) -> bool:
    markers = ("хронолог", "сравни", "сводк", "обзор", "по всем документам", "итог", "таймлайн")
    return any(m in f.question_lower for m in markers)


def _has_contradiction_semantics(f: QueryFeatures) -> bool:
    markers = ("противореч", "расхожд", "несоответств")
    return any(m in f.question_lower for m in markers)


def _has_deep_analysis_semantics(f: QueryFeatures) -> bool:
    markers = (
        "проанализируй",
        "правовая позиция",
        "соответствует ли",
        "нарушение",
        "риски",
        "оцени риск",
    )
    return any(m in f.question_lower for m in markers)


def _has_legal_corpus_semantics(f: QueryFeatures) -> bool:
    markers = ("закон", "статья", "кодекс", "норма", "правовая позиция")
    return any(m in f.question_lower for m in markers)


def classify_case_assistant_intent(f: QueryFeatures) -> CaseAssistantIntent:
    """
    Priority-ordered intent resolution (first match wins).

    Order reflects product precedence: safety/clarify → corpus overview →
    cross-doc → drill-down → narrow fact → default case Q&A.
    """
    if not f.question_lower:
        return CaseAssistantIntent(
            primary="empty",
            task_type="clarification",
            depth_tier="fast",
            response_shape="fact",
            clarification_needed=True,
            reason="empty_question",
            confidence=0.99,
        )

    if f.draft_mode:
        return CaseAssistantIntent(
            primary="drafting",
            task_type="drafting",
            depth_tier="deep",
            response_shape="analysis",
            clarification_needed=False,
            reason="draft_mode",
            confidence=0.98,
        )

    if f.char_len < 4:
        return CaseAssistantIntent(
            primary="too_short",
            task_type="clarification",
            depth_tier="fast",
            response_shape="fact",
            clarification_needed=True,
            reason="too_short_query",
            confidence=0.93,
        )

    from app.services.chat.case_metadata_service import is_case_metadata_question

    if is_case_metadata_question(f.question_lower):
        return CaseAssistantIntent(
            primary="case_metadata",
            task_type="fact_lookup",
            depth_tier="fast",
            response_shape="fact",
            clarification_needed=False,
            reason="case_card_metadata",
            confidence=0.96,
        )

    if _has_clarification_request(f):
        return CaseAssistantIntent(
            primary="needs_clarification",
            task_type="clarification",
            depth_tier="fast",
            response_shape="fact",
            clarification_needed=True,
            reason="clarification_request",
            confidence=0.9,
        )

    if _has_contradiction_semantics(f):
        return CaseAssistantIntent(
            primary="contradiction",
            task_type="contradiction_check",
            depth_tier="deep",
            response_shape="analysis",
            clarification_needed=False,
            reason="contradiction_semantics",
            confidence=0.9,
        )

    multi_doc_scope = f.effective_doc_scope >= 2 or f.attached_files_count > 1

    if multi_doc_scope and _has_synthesis_semantics(f):
        return CaseAssistantIntent(
            primary="cross_doc_analysis",
            task_type="multi_doc_synthesis",
            depth_tier="deep",
            response_shape="analysis",
            clarification_needed=False,
            reason="cross_doc_synthesis",
            confidence=0.88,
        )

    if f.legal_research and _has_legal_corpus_semantics(f):
        return CaseAssistantIntent(
            primary="legal_analysis",
            task_type="legal_reasoning",
            depth_tier="deep",
            response_shape="analysis",
            clarification_needed=False,
            reason="legal_research_query",
            confidence=0.85,
        )

    if f.deep_think:
        return CaseAssistantIntent(
            primary="legal_analysis",
            task_type="legal_reasoning",
            depth_tier="deep",
            response_shape="analysis",
            clarification_needed=False,
            reason="deep_think_enabled",
            confidence=0.8,
        )

    overview_hit = _has_overview_semantics(f) or (
        multi_doc_scope and _has_plural_doc_scope(f) and f.word_count <= 24
    )
    if multi_doc_scope and overview_hit:
        depth: DepthTierLabel = "fast" if f.char_len <= 120 else "deep"
        return CaseAssistantIntent(
            primary="case_corpus_overview",
            task_type="multi_doc_synthesis",
            depth_tier=depth,
            response_shape="executive_summary",
            clarification_needed=False,
            reason="case_corpus_overview",
            confidence=0.88,
        )

    if f.attached_files_count > 3 and ("все" in f.question_lower or "обзор" in f.question_lower):
        return CaseAssistantIntent(
            primary="case_corpus_overview",
            task_type="multi_doc_synthesis",
            depth_tier="deep",
            response_shape="executive_summary",
            clarification_needed=False,
            reason="multi_docs_attached_overview",
            confidence=0.8,
        )

    if _has_single_named_doc_question(f):
        shape: ResponseShapeLabel = (
            "executive_summary" if "кратко" in f.question_lower else "memorandum"
        )
        return CaseAssistantIntent(
            primary="standard_case_qa",
            task_type="single_doc_extraction",
            depth_tier="fast",
            response_shape=shape,
            clarification_needed=False,
            reason="single_named_doc_question",
            confidence=0.87,
        )

    if _has_drill_down_semantics(f):
        return CaseAssistantIntent(
            primary="drill_down",
            task_type="legal_reasoning",
            depth_tier="fast",
            response_shape="memorandum",
            clarification_needed=False,
            reason="drill_down_semantics",
            confidence=0.84,
        )

    if _has_deep_analysis_semantics(f):
        return CaseAssistantIntent(
            primary="legal_analysis",
            task_type="multi_doc_synthesis",
            depth_tier="deep",
            response_shape="analysis",
            clarification_needed=False,
            reason="deep_analysis_semantics",
            confidence=0.82,
        )

    if _has_narrow_fact_semantics(f):
        return CaseAssistantIntent(
            primary="narrow_fact",
            task_type="fact_lookup" if _FACT_POINT_RE.search(f.question_lower) else "single_doc_extraction",
            depth_tier="fast",
            response_shape="fact",
            clarification_needed=False,
            reason="narrow_fact_semantics",
            confidence=0.86,
        )

    if f.attached_files_count > 1 and not _has_narrow_fact_semantics(f) and f.char_len <= 220:
        return CaseAssistantIntent(
            primary="case_corpus_overview",
            task_type="multi_doc_synthesis",
            depth_tier="fast",
            response_shape="executive_summary",
            clarification_needed=False,
            reason="multi_doc_attached_default",
            confidence=0.74,
        )

    if f.char_len <= 220:
        shape: ResponseShapeLabel = "fact" if f.char_len <= 80 else "memorandum"
        return CaseAssistantIntent(
            primary="standard_case_qa",
            task_type="single_doc_extraction",
            depth_tier="fast",
            response_shape=shape,
            clarification_needed=False,
            reason="standard_case_qa_short",
            confidence=0.68,
        )

    return CaseAssistantIntent(
        primary="legal_analysis",
        task_type="legal_reasoning",
        depth_tier="deep",
        response_shape="analysis",
        clarification_needed=False,
        reason="default_deep_path",
        confidence=0.62,
    )


def resolve_case_assistant_intent(
    *,
    question: str,
    attached_files_count: int = 0,
    corpus_size: int = 0,
    draft_mode: bool = False,
    legal_research: bool = False,
    deep_think: bool = False,
) -> CaseAssistantIntent:
    """Public entry: classify one turn."""
    features = extract_query_features(
        question=question,
        attached_files_count=attached_files_count,
        corpus_size=corpus_size,
        draft_mode=draft_mode,
        legal_research=legal_research,
        deep_think=deep_think,
    )
    return classify_case_assistant_intent(features)


def intent_to_policy_tuple(
    intent: CaseAssistantIntent,
) -> Tuple[TaskTypeLabel, DepthTierLabel, bool, str, float]:
    """Legacy tuple for ConversationPolicyService.infer_task_and_depth callers."""
    return (
        intent.task_type,
        intent.depth_tier,
        intent.clarification_needed,
        intent.reason,
        intent.confidence,
    )
