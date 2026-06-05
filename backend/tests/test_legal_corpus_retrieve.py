"""Тесты пайплайна retrieve_legal_corpus_documents и merge глобального ассистента."""

from __future__ import annotations

from typing import List

from langchain_core.documents import Document

from app.config import config
from app.services.chat.global_langgraph_service import _merge_matter_and_law_hits


def test_merge_matter_and_law_reserves_law_slots(monkeypatch):
    monkeypatch.setattr(config, "LEGAL_CORPUS_GLOBAL_MERGE_MIN_SLOTS", 3, raising=False)
    matter = [{"source_type": "document", "source_id": "f1", "text": "x" * 200, "score": 100.0}]
    law = [
        {"source_type": "legal_corpus", "source_id": "a", "text": "a1", "score": 0.1},
        {"source_type": "legal_corpus", "source_id": "b", "text": "b1", "score": 0.2},
        {"source_type": "legal_corpus", "source_id": "c", "text": "c1", "score": 0.05},
    ]
    merged = _merge_matter_and_law_hits(matter, law, route="hybrid", cap=4)
    legal = [h for h in merged if h.get("source_type") == "legal_corpus"]
    assert len(legal) >= 3
    assert len(merged) == 4


def test_retrieve_legal_corpus_recall_cap_without_rerank(monkeypatch):
    from app.services import legal_corpus_service as lcs

    monkeypatch.setattr(lcs, "should_skip_retrieval_for_message", lambda _q: False)
    monkeypatch.setattr(lcs, "count_corpus_chunks", lambda: 1)
    monkeypatch.setattr(config, "LEGAL_CORPUS_RECALL_MAX", 5, raising=False)
    monkeypatch.setattr(config, "LEGAL_CORPUS_USE_RERANKER", False, raising=False)

    docs_in: List[Document] = [
        Document(page_content=f"chunk{i}", metadata={"chunk_id": f"id{i}"}) for i in range(12)
    ]

    def _fake_hybrid(q: str, k: int, instrument_ids=None):
        return list(docs_in[: max(k, 1)])

    monkeypatch.setattr(lcs, "_run_assistant_hybrid_search", _fake_hybrid)
    monkeypatch.setattr(lcs, "_run_dense_search", lambda *a, **k: [])
    monkeypatch.setattr(lcs, "_run_fts_bm25_search", lambda *a, **k: [])
    monkeypatch.setattr(lcs, "_run_lexical_search", lambda *a, **k: [])

    out = lcs.retrieve_legal_corpus_documents(
        "тестовый запрос про банкротство",
        k=3,
        instrument_ids=None,
        search_queries=None,
    )
    assert len(out) == 3


def test_retrieve_legal_corpus_rerank_reorders(monkeypatch):
    from app.services import legal_corpus_service as lcs

    monkeypatch.setattr(lcs, "should_skip_retrieval_for_message", lambda _q: False)
    monkeypatch.setattr(lcs, "count_corpus_chunks", lambda: 1)
    monkeypatch.setattr(config, "LEGAL_CORPUS_RECALL_MAX", 10, raising=False)
    monkeypatch.setattr(config, "LEGAL_CORPUS_USE_RERANKER", True, raising=False)
    monkeypatch.setattr(config, "LEGAL_CORPUS_RERANK_MAX_CHARS", 500, raising=False)

    d0 = Document(page_content="торги должник", metadata={"chunk_id": "0"})
    d1 = Document(page_content="оспаривание сделки должника", metadata={"chunk_id": "1"})

    monkeypatch.setattr(
        lcs,
        "_run_assistant_hybrid_search",
        lambda q, k, instrument_ids=None: [d0, d1],
    )
    monkeypatch.setattr(lcs, "_run_dense_search", lambda *a, **k: [])
    monkeypatch.setattr(lcs, "_run_fts_bm25_search", lambda *a, **k: [])
    monkeypatch.setattr(lcs, "_run_lexical_search", lambda *a, **k: [])

    class _FakeReranker:
        def rerank(self, query, documents, top_k=10, score_threshold=None):
            # «Лучше» второй документ для запроса про оспаривание
            order = sorted(
                list(enumerate(documents)),
                key=lambda ix_d: ix_d[1].page_content.count("оспаривание"),
                reverse=True,
            )
            return [(d, float(1.0 - 0.1 * i)) for i, (_, d) in enumerate(order[:top_k])]

    fake = _FakeReranker()

    monkeypatch.setattr(
        "app.services.reranker_service.get_reranker_service",
        lambda: fake,
    )

    out = lcs.retrieve_legal_corpus_documents(
        "оспорить сделку должника",
        k=1,
        instrument_ids=None,
    )
    assert len(out) == 1
    assert "оспаривание" in (out[0].page_content or "")


def test_embedding_synonym_hint_fz127(monkeypatch):
    from app.services.legal_chunker import _apply_hidden_embedding_context

    monkeypatch.setattr(config, "LEGAL_CORPUS_EMBED_SYNONYM_HINTS_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "LEGAL_CHUNK_EMBED_PREFIX_ENABLED", True, raising=False)
    docs = [
        Document(
            page_content="текст нормы",
            metadata={
                "instrument_id": "fz-127",
                "instrument_short_name": "ФЗ-127",
                "section_title": "Статья 1",
                "parent_path": [],
            },
        )
    ]
    _apply_hidden_embedding_context(docs, enabled=True)
    et = docs[0].metadata.get("embedding_text") or ""
    assert "оспаривание" in et.lower()
