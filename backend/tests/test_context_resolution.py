"""Tests for parent context resolution (micro rerank → macro LLM context)."""
from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.documents import Document

from app.services.chat.context_resolution import (
    filter_rerank_pool_to_micro,
    resolve_parent_context,
)


def _micro(fid: str, pid: str, text: str = "micro", score: float = 0.9) -> Document:
    return Document(
        page_content=text,
        metadata={
            "chunk_level": "micro",
            "chunk_id": f"m_{fid}",
            "parent_macro_id": pid,
            "file_id": fid,
            "rerank_score": score,
            "char_start": 10,
            "char_end": 50,
        },
    )


def _macro(pid: str, text: str = "macro full clause text") -> Document:
    return Document(
        page_content=text,
        metadata={
            "chunk_level": "macro",
            "macro_id": pid,
            "chunk_id": f"mac_{pid}",
            "file_id": "f1",
        },
    )


def test_filter_rerank_pool_drops_macro():
    docs = [_micro("f1", "p1"), _macro("p2"), _micro("f1", "p2")]
    out = filter_rerank_pool_to_micro(docs)
    assert len(out) == 2
    assert all(d.metadata.get("chunk_level") != "macro" for d in out)


def test_resolve_parent_context_deduplicates_parents():
    store = MagicMock()
    store.fetch_macro_chunks_by_macro_ids.return_value = {
        "p1": _macro("p1", "Parent one full text"),
        "p2": _macro("p2", "Parent two full text"),
    }
    ranked = [
        _micro("f1", "p1", score=0.95),
        _micro("f1", "p1", score=0.80),
        _micro("f1", "p2", score=0.70),
    ]
    resolved, meta = resolve_parent_context(ranked, case_id="case1", vector_store=store)
    assert len(resolved) == 2
    assert resolved[0].page_content == "Parent one full text"
    assert resolved[1].page_content == "Parent two full text"
    assert meta["parents_resolved"] == 2
    assert resolved[0].metadata.get("grounding_micro_chunk_id") == "m_f1"


def test_resolve_parent_context_fallback_to_micro_when_macro_missing():
    store = MagicMock()
    store.fetch_macro_chunks_by_macro_ids.return_value = {}
    micro = _micro("f1", "missing_parent")
    resolved, meta = resolve_parent_context([micro], case_id="c1", vector_store=store)
    assert len(resolved) == 1
    assert resolved[0].page_content == "micro"
    assert meta["fallback_micro"] == 1


def test_resolve_parent_preserves_rerank_order():
    store = MagicMock()
    store.fetch_macro_chunks_by_macro_ids.return_value = {
        "pA": _macro("pA", "A"),
        "pB": _macro("pB", "B"),
    }
    ranked = [_micro("f", "pB", score=0.99), _micro("f", "pA", score=0.50)]
    resolved, _ = resolve_parent_context(ranked, case_id="c1", vector_store=store)
    assert [d.page_content for d in resolved] == ["B", "A"]
