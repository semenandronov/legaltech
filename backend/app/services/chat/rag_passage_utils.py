"""Shared helpers for RAG rerank passages (case assistant + legal corpus)."""
from __future__ import annotations

from langchain_core.documents import Document


def legal_corpus_max_fragment_chars() -> int:
    from app.config import config

    return int(getattr(config, "LEGAL_CORPUS_MAX_FRAGMENT_CHARS", 2800) or 2800)


def truncate_passage_body(text: str, max_chars: int) -> str:
    """Обрезка тела фрагмента для контекста LLM (равномерный бюджет по слотам)."""
    t = (text or "").strip()
    cap = int(max_chars)
    if cap <= 0 or len(t) <= cap:
        return t
    return t[:cap].rstrip() + "…"


def passage_for_rerank(doc: Document, max_chars: int) -> str:
    """Build a compact passage string for cross-encoder reranking."""
    m = doc.metadata or {}
    title = str(m.get("section_title") or m.get("source_file") or "").strip()
    body = (doc.page_content or "").strip()
    head = f"{title}\n\n" if title else ""
    rest = max(256, int(max_chars) - len(head))
    text = (head + body[:rest]).strip()
    return text or body[: int(max_chars)]
