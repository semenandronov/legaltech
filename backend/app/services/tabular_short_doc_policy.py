"""Short-document policy for tabular cells: full text instead of chunk RAG."""
from __future__ import annotations

from typing import List, Optional, Tuple

from langchain_core.documents import Document

from app.config import config


def tabular_short_doc_full_text_enabled() -> bool:
    return bool(getattr(config, "TABULAR_SHORT_DOC_FULL_TEXT", True))


def tabular_short_doc_max_chars() -> int:
    raw = int(getattr(config, "TABULAR_SHORT_DOC_MAX_CHARS", 18000) or 18000)
    return max(2000, raw)


def should_use_short_doc_full_text(original_text: str) -> bool:
    if not tabular_short_doc_full_text_enabled():
        return False
    text = (original_text or "").strip()
    if not text:
        return False
    return len(text) <= tabular_short_doc_max_chars()


def build_short_doc_cell_context(
    *,
    original_text: str,
    file_id: str,
    filename: str = "",
    max_chars: Optional[int] = None,
) -> Tuple[str, List[Document]]:
    """
    Build a single-span context for short files.

    Truncates only if text somehow exceeds the policy budget (defensive).
    """
    text = (original_text or "").strip()
    budget = max_chars if max_chars is not None else tabular_short_doc_max_chars()
    if len(text) > budget:
        text = text[:budget]
    doc = Document(
        page_content=text,
        metadata={
            "file_id": str(file_id),
            "source_file": filename or "",
            "char_start": 0,
            "char_end": len(text),
            "zone": "full_document",
            "retrieval_channel": "short_doc_full_text",
        },
    )
    return text, [doc]
