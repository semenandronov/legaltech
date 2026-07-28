"""Coverage gate before tabular LLM extract."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Sequence

from langchain_core.documents import Document

from app.services.chat.retrieval_escalation import question_anchors_covered

CoverageVerdict = Literal["sufficient", "weak"]


@dataclass(frozen=True)
class CoverageGateResult:
    verdict: CoverageVerdict
    reason: str


def _doc_text(doc: Document) -> str:
    return str(getattr(doc, "page_content", "") or "")


def _lexical_hits(docs: Sequence[Document], terms: Sequence[str]) -> bool:
    if not terms:
        return True
    blob = " ".join(_doc_text(d) for d in docs).lower()
    for term in terms:
        t = str(term).strip().lower()
        if len(t) >= 2 and t in blob:
            return True
    return False


def _top_rerank_score(docs: Sequence[Document]) -> float:
    best = 0.0
    for doc in docs:
        md = doc.metadata or {}
        for key in ("rerank_score", "combined_score", "similarity_score", "score"):
            raw = md.get(key)
            if raw is None:
                continue
            try:
                best = max(best, float(raw))
            except (TypeError, ValueError):
                continue
    return best


def evaluate_tabular_coverage(
    *,
    question: str,
    docs: Sequence[Document],
    lexical_terms: Sequence[str],
    exact_literals: Sequence[str],
    column_type: str,
    recall_meta: Optional[Dict[str, Any]] = None,
) -> CoverageGateResult:
    if not docs:
        return CoverageGateResult("weak", "no_docs")

    anchor_q = " ".join(
        [
            question or "",
            " ".join(str(t) for t in lexical_terms if str(t).strip()),
            " ".join(str(t) for t in exact_literals if str(t).strip()),
        ]
    ).strip()
    if anchor_q and not question_anchors_covered(anchor_q, docs):
        if lexical_terms and not _lexical_hits(docs, lexical_terms):
            return CoverageGateResult("weak", "anchors_and_lexical_missing")

    if lexical_terms and not _lexical_hits(docs, [*lexical_terms, *exact_literals]):
        if column_type in ("verbatim", "text", "yes_no"):
            if _top_rerank_score(docs) < 0.12:
                return CoverageGateResult("weak", "low_rerank_no_lexical")

    recall_n = 0
    if isinstance(recall_meta, dict):
        try:
            recall_n = int(recall_meta.get("recall_docs") or len(docs))
        except (TypeError, ValueError):
            recall_n = len(docs)
    if recall_n < 1:
        return CoverageGateResult("weak", "empty_recall_meta")

    return CoverageGateResult("sufficient", "ok")
