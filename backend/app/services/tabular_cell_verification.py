"""
Post-extraction verification for tabular cells (evidence-first, before persist).

Separates LLM output from trust decisions — no DB access required for core checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from langchain_core.documents import Document

from app.models.case import File
from app.models.tabular_review import TabularColumn
from app.services.tabular_extraction_policy import (
    column_requires_evidence,
    is_na_cell_value,
)
from app.services.tabular_quote_then_answer import (
    normalize_for_grounding,
    quote_grounded_in_corpus,
)
from app.services.tabular_review_models import TabularCellExtractionModel


@dataclass(frozen=True)
class EvidenceAssessment:
    has_model_references: bool
    has_verbatim: bool
    has_chunk_provenance: bool
    quote_grounded_in_document: bool
    quote_grounded_in_context: bool = False
    date_grounded_in_document: bool = False

    @property
    def has_sufficient_evidence(self) -> bool:
        """
        Non-N/A answers require a model-provided citation that is grounded in the
        document or retrieval corpus. Chunk provenance alone is never enough —
        retrieval always returns chunks with offsets.
        """
        if self.date_grounded_in_document:
            return True
        has_model_cite = self.has_verbatim or self.has_model_references
        if not has_model_cite:
            return False
        return self.quote_grounded_in_document or self.quote_grounded_in_context


@dataclass
class CellVerificationOutcome:
    result: TabularCellExtractionModel
    issues: List[str] = field(default_factory=list)
    evidence: Optional[EvidenceAssessment] = None
    forced_na: bool = False
    needs_review: bool = False


def _normalize_for_substring_match(text: str) -> str:
    return normalize_for_grounding(text)


def quote_exists_in_document(quote: str, file: File, *, min_len: int = 12) -> bool:
    """Check anchor text appears in file.original_text."""
    return quote_grounded_in_corpus(quote, file.original_text or "", min_len=min_len)


def _included_docs_corpus(included_docs: List[Document]) -> str:
    parts: List[str] = []
    for doc in included_docs or []:
        text = (doc.page_content or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def _model_evidence_anchor(result: TabularCellExtractionModel) -> str:
    verbatim = (result.verbatim_extract or "").strip()
    if len(verbatim) >= 12:
        return verbatim
    refs = result.source_references if isinstance(result.source_references, list) else []
    for r in refs:
        if isinstance(r, dict):
            anchor = str(r.get("text") or "").strip()
            if len(anchor) >= 12:
                return anchor
    return ""


def date_value_grounded_in_document(normalized_iso: str, file: File) -> bool:
    from app.services.date_validator import normalized_date_in_document

    return normalized_date_in_document(normalized_iso, file.original_text or "")


def assess_evidence(
    result: TabularCellExtractionModel,
    file: File,
    included_docs: List[Document],
    *,
    column_type: Optional[str] = None,
) -> EvidenceAssessment:
    refs = result.source_references if isinstance(result.source_references, list) else []
    has_model_refs = any(
        isinstance(r, dict) and str(r.get("text") or "").strip()
        for r in refs
    )
    verbatim = (result.verbatim_extract or "").strip()
    has_verbatim = len(verbatim) >= 12

    has_provenance = False
    for doc in included_docs or []:
        meta = doc.metadata or {}
        if meta.get("char_start") is not None and meta.get("char_end") is not None:
            has_provenance = True
            break
        if meta.get("source_page") is not None:
            has_provenance = True
            break

    anchor = _model_evidence_anchor(result)
    grounded_doc = quote_exists_in_document(anchor, file) if anchor else False
    corpus = _included_docs_corpus(included_docs)
    grounded_ctx = quote_grounded_in_corpus(anchor, corpus) if anchor and corpus else False

    date_grounded = False
    if column_type == "date":
        normalized = (result.normalized_value or result.cell_value or "").strip()
        if normalized and not is_na_cell_value(normalized):
            date_grounded = date_value_grounded_in_document(normalized, file)

    return EvidenceAssessment(
        has_model_references=has_model_refs,
        has_verbatim=has_verbatim,
        has_chunk_provenance=has_provenance,
        quote_grounded_in_document=grounded_doc,
        quote_grounded_in_context=grounded_ctx,
        date_grounded_in_document=date_grounded,
    )


def apply_evidence_first_policy(
    result: TabularCellExtractionModel,
    *,
    column: TabularColumn,
    file: File,
    included_docs: List[Document],
) -> CellVerificationOutcome:
    """
    Enforce evidence rules on LLM output before persistence.

    Any evidence-required column without a grounded model citation → N/A.
    Descriptive soft-keep is intentionally removed: ungrounded answers are rejected.
    """
    issues: List[str] = []
    if is_na_cell_value(result.cell_value):
        return CellVerificationOutcome(result=result, issues=issues)

    if not column_requires_evidence(column):
        return CellVerificationOutcome(result=result, issues=issues)

    evidence = assess_evidence(result, file, included_docs, column_type=column.column_type)

    if evidence.has_sufficient_evidence:
        return CellVerificationOutcome(result=result, issues=issues, evidence=evidence)

    issues.append("missing_evidence")
    downgraded = result.model_copy(
        update={
            "cell_value": "N/A",
            "normalized_value": "N/A",
            "confidence": 0.0,
            "reasoning": (
                (result.reasoning or "")
                + " Ответ отклонён: нет подтверждающей цитаты, дословно найденной "
                "в документе или во фрагментах retrieval."
            ).strip(),
        }
    )
    return CellVerificationOutcome(
        result=downgraded,
        issues=issues,
        evidence=evidence,
        forced_na=True,
    )
