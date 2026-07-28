"""Unit tests for tabular multi-query hybrid merge helpers."""
from __future__ import annotations

from types import SimpleNamespace

from langchain_core.documents import Document

from app.services.tabular_context_compiler import (
    _dedupe_recall_docs,
    _resolve_search_queries,
)


def test_resolve_search_queries_dedupes_and_caps():
    params = SimpleNamespace(
        search_queries=(
            "Material Adverse Effect",
            "material adverse effect",
            "would reasonably be expected",
            "taken as a whole",
            "extra fifth",
        )
    )
    out = _resolve_search_queries(params, "Material Adverse Effect definition")
    assert out[0] == "Material Adverse Effect definition"
    assert len(out) <= 4
    lowers = [q.lower() for q in out]
    assert len(lowers) == len(set(lowers))


def test_dedupe_recall_docs_by_identity():
    a = Document(page_content="aaa", metadata={"chunk_id": "1", "file_id": "f"})
    b = Document(page_content="aaa", metadata={"chunk_id": "1", "file_id": "f"})
    c = Document(page_content="bbb", metadata={"chunk_id": "2", "file_id": "f"})
    out = _dedupe_recall_docs([a, b, c])
    assert len(out) == 2
