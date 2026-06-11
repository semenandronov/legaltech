"""Legal reference retrieval for Draft section generation (case docs use CaseRetrievalSnapshot)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MAX_LEGAL_SNIPPET = 1400


def retrieve_legal_reference_context(*, query: str, k: int = 4) -> str:
    """Fetch normative reference snippets for legal sections (not case document RAG)."""
    q = (query or "").strip()
    if not q:
        return ""
    try:
        from app.services.legal_corpus_service import retrieve_legal_corpus_context

        block = retrieve_legal_corpus_context(query=q, k=k)
        if block:
            return f"[Справочные нормы]\n{block[:_MAX_LEGAL_SNIPPET]}"
    except Exception as exc:
        logger.debug("[draft_pipeline.legal_rag] skipped: %s", exc)
    return ""
