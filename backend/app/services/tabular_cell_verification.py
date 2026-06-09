"""
Post-extraction verification for tabular cells (evidence-first, before persist).

Separates LLM output from trust decisions — no DB access required for core checks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from app.models.case import File
from app.models.tabular_review import TabularColumn
from app.services.tabular_extraction_policy import (
    column_is_fact_type,
    column_requires_evidence,
    is_na_cell_value,
)
from app.services.tabular_review_models import TabularCellExtractionModel


@dataclass(frozen=True)
class EvidenceAssessment:
    has_model_references: bool
    has_verbatim: bool
    has_chunk_provenance: bool
    quote_grounded_in_document: bool
    date_grounded_in_document: bool = False

    @property
    def has_sufficient_evidence(self) -> bool:
        if self.has_chunk_provenance or self.has_verbatim:
            return True
        if self.date_grounded_in_document:
            return True
        if self.has_model_references and self.quote_grounded_in_document:
            return True
        return False


@dataclass
class CellVerificationOutcome:
    result: TabularCellExtractionModel
    issues: List[str] = field(default_factory=list)
    evidence: Optional[EvidenceAssessment] = None
    forced_na: bool = False
    needs_review: bool = False


def _normalize_for_substring_match(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def quote_exists_in_document(quote: str, file: File, *, min_len: int = 12) -> bool:
    """Check anchor text appears in file.original_text."""
    q = _normalize_for_substring_match(quote)
    if len(q) < min_len:
        return False
    doc = _normalize_for_substring_match(file.original_text or "")
    if not doc:
        return False
    return q in doc


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

    anchor = verbatim
    if not anchor and refs:
        for r in refs:
            if isinstance(r, dict):
                anchor = str(r.get("text") or "").strip()
                if anchor:
                    break
    if not anchor:
        anchor = (result.cell_value or "").strip()[:240]

    grounded = quote_exists_in_document(anchor, file) if anchor else False
    date_grounded = False
    if column_type == "date":
        normalized = (result.normalized_value or result.cell_value or "").strip()
        if normalized and not is_na_cell_value(normalized):
            date_grounded = date_value_grounded_in_document(normalized, file)

    return EvidenceAssessment(
        has_model_references=has_model_refs,
        has_verbatim=has_verbatim,
        has_chunk_provenance=has_provenance,
        quote_grounded_in_document=grounded,
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
    Enforce Harvey-style evidence rules on LLM output before persistence.

    - Fact columns without evidence → N/A (never hallucinated facts).
    - Descriptive text without evidence → keep value but flag needs_review.
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

    if column_is_fact_type(column.column_type):
        downgraded = result.model_copy(
            update={
                "cell_value": "N/A",
                "normalized_value": "N/A",
                "confidence": 0.0,
                "reasoning": (
                    (result.reasoning or "")
                    + " Ответ отклонён: для данного типа колонки требуется подтверждение "
                    "цитатой из документа; подходящий фрагмент не найден."
                ).strip(),
            }
        )
        return CellVerificationOutcome(
            result=downgraded,
            issues=issues,
            evidence=evidence,
            forced_na=True,
        )

    # Summary / free-text: retain answer but force human review.
    reviewed = result.model_copy(
        update={
            "confidence": min(float(result.confidence), 0.45),
            "reasoning": (
                (result.reasoning or "")
                + " Требуется проверка: ответ не подкреплён цитатой из документа."
            ).strip(),
        }
    )
    return CellVerificationOutcome(
        result=reviewed,
        issues=issues,
        evidence=evidence,
        needs_review=True,
    )
