"""Single entry point for Docling-aware document chunking with structure routing."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from app.services.document_structure_classifier import classify_indexing_strategy
from app.services.legal_chunker import (
    LegalChunkerV2,
    _collect_legal_segments,
    _normalize_docling_segments,
)
from app.services.structured_table_indexer import StructuredTableIndexer

logger = logging.getLogger(__name__)


def build_index_chunks(
    *,
    content_bytes: Optional[bytes],
    filename: str,
    base_metadata: Dict[str, Any],
    doc_type: Optional[str] = None,
    case_id: Optional[str] = None,
    fallback_text: Optional[str] = None,
    loader_did_ocr: bool = False,
    loader_native_text: bool = False,
    loader_documents: Optional[List[Document]] = None,
    use_norm_corpus: bool = False,
) -> List[Document]:
    """
    Run Docling pre-segmentation once, route to structured-table or narrative indexer.

    OCR / corpus norm paths bypass structured routing and delegate to LegalChunkerV2.
    """
    if use_norm_corpus:
        return LegalChunkerV2().chunk_corpus_norms(
            content_bytes=content_bytes,
            filename=filename,
            base_metadata=base_metadata,
            doc_type=doc_type,
            case_id=case_id,
            fallback_text=fallback_text,
            loader_did_ocr=loader_did_ocr,
            loader_native_text=loader_native_text,
            loader_documents=loader_documents,
        )

    if loader_did_ocr:
        return LegalChunkerV2().chunk(
            content_bytes=content_bytes,
            filename=filename,
            base_metadata=base_metadata,
            doc_type=doc_type,
            case_id=case_id,
            fallback_text=fallback_text,
            loader_did_ocr=loader_did_ocr,
            loader_native_text=loader_native_text,
            loader_documents=loader_documents,
        )

    segments, full_text, preseg_strategy, profile = _collect_legal_segments(
        content_bytes=content_bytes,
        filename=filename,
        doc_type=doc_type,
        case_id=case_id,
        fallback_text=fallback_text,
        loader_did_ocr=loader_did_ocr,
        loader_native_text=loader_native_text,
        loader_documents=loader_documents,
        apply_segment_normalization=False,
    )
    if not segments:
        raise ValueError(f"build_index_chunks: empty segment list for {filename}")

    strategy = classify_indexing_strategy(
        segments,
        full_text=full_text,
        doc_type=doc_type,
    )

    if strategy == "structured_table":
        logger.info(
            "[document_indexing] %s → structured_table (preseg=%s)",
            filename,
            preseg_strategy,
        )
        return StructuredTableIndexer().index(
            segments=segments,
            full_text=full_text,
            base_metadata=base_metadata,
            preseg_strategy=preseg_strategy,
            filename=filename,
            profile=profile,
            doc_type=doc_type,
        )

    normalized = _normalize_docling_segments(list(segments), profile)
    return LegalChunkerV2().chunk_from_segments(
        segments=normalized,
        full_text=full_text,
        preseg_strategy=preseg_strategy,
        profile=profile,
        base_metadata=base_metadata,
        filename=filename,
    )
