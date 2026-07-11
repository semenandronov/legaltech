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

    monkeypatch.setattr(lcs, "_run_norm_hybrid_search", _fake_hybrid)
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
        "_run_norm_hybrid_search",
        lambda q, k, instrument_ids=None: [d0, d1],
    )
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
        "app.services.reranker_service.get_reranker_for_tier",
        lambda _tier: fake,
    )

    out = lcs.retrieve_legal_corpus_documents(
        "оспорить сделку должника",
        k=1,
        instrument_ids=None,
    )
    assert len(out) == 1
    assert "оспаривание" in (out[0].page_content or "")


def test_norm_hybrid_search_single_embed(monkeypatch):
    from app.services import legal_corpus_service as lcs

    embed_calls: list = []
    hybrid_calls: list = []

    def _fake_embed(q: str):
        embed_calls.append(q)
        return [0.1] * 256

    class _FakeProcessor:
        def hybrid_search(self, **kwargs):
            hybrid_calls.append(kwargs)
            return [Document(page_content="ст 33", metadata={"chunk_level": "norm"})]

    monkeypatch.setattr(lcs, "_embed_legal_search_query", _fake_embed)
    monkeypatch.setattr(lcs, "get_document_processor", lambda: _FakeProcessor())

    out = lcs._run_norm_hybrid_search("порог банкротства", k=5, instrument_ids=["fz-127"])
    assert len(out) == 1
    assert len(embed_calls) == 1
    assert embed_calls[0] == "порог банкротства"
    assert hybrid_calls[0]["chunk_levels"] == ["norm"]
    assert hybrid_calls[0]["query_embedding"] == [0.1] * 256
    assert hybrid_calls[0]["bm25_sync"] is False
    assert hybrid_calls[0]["case_id"] == lcs.LEGAL_CORPUS_CASE_ID


def test_retrieve_legal_corpus_per_query_rerank(monkeypatch):
    from app.services import legal_corpus_service as lcs

    monkeypatch.setattr(lcs, "should_skip_retrieval_for_message", lambda _q: False)
    monkeypatch.setattr(lcs, "count_corpus_chunks", lambda: 1)
    monkeypatch.setattr(config, "LEGAL_CORPUS_USE_RERANKER", True, raising=False)
    monkeypatch.setattr(config, "LEGAL_CORPUS_CONTEXT_K", 8, raising=False)

    d_citizen = Document(page_content="гражданин пятьсот тысяч", metadata={"chunk_id": "c", "article_number": "213.3"})
    d_ul = Document(page_content="юрлицо два миллиона", metadata={"chunk_id": "u", "article_number": "33"})
    d_noise = Document(page_content="опубликование сведений", metadata={"chunk_id": "n", "article_number": "213.7"})

    rerank_queries: list = []

    def _fake_hybrid(q: str, k: int, instrument_ids=None):
        if "пятьсот" in q:
            return [d_citizen, d_noise]
        if "два миллиона" in q:
            return [d_ul, d_noise]
        return [d_noise]

    class _FakeReranker:
        def rerank(self, query, documents, top_k=10, score_threshold=None):
            rerank_queries.append(query)
            q = (query or "").lower()
            scored = []
            for i, d in enumerate(documents):
                text = (d.page_content or "").lower()
                score = 1.0
                if "пятьсот" in q and "пятьсот" in text:
                    score = 10.0
                elif "два миллиона" in q and "два миллиона" in text:
                    score = 10.0
                elif "опубликование" in text:
                    score = 0.1
                scored.append((d, score - i * 0.01))
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]

    monkeypatch.setattr(lcs, "_run_norm_hybrid_search", _fake_hybrid)
    monkeypatch.setattr(lcs, "_run_fts_bm25_search", lambda *a, **k: [])
    monkeypatch.setattr(lcs, "_run_lexical_search", lambda *a, **k: [])
    monkeypatch.setattr("app.services.reranker_service.get_reranker_for_tier", lambda _tier: _FakeReranker())

    out = lcs.retrieve_legal_corpus_documents(
        "сравнение гражданина и юрлица при банкротстве",
        k=4,
        instrument_ids=["fz-127"],
        search_queries=[
            "возбуждение банкротства гражданина пятьсот тысяч рублей",
            "совокупность требований два миллиона рублей юридическое лицо",
        ],
        include_original_query=False,
    )

    arts = {str((d.metadata or {}).get("article_number")) for d in out}
    assert "213.3" in arts
    assert "33" in arts
    assert "пятьсот" in rerank_queries[0] or "пятьсот" in " ".join(rerank_queries).lower()
    assert len(rerank_queries) >= 2


def test_finalize_merged_legal_docs_article_diversity():
    from app.services.legal_corpus_service import _finalize_merged_legal_docs

    docs = [
        Document(page_content="a1", metadata={"chunk_id": "1", "article_number": "3"}),
        Document(page_content="a2", metadata={"chunk_id": "2", "article_number": "3"}),
        Document(page_content="b1", metadata={"chunk_id": "3", "article_number": "33"}),
        Document(page_content="c1", metadata={"chunk_id": "4", "article_number": "213.3"}),
    ]
    out = _finalize_merged_legal_docs(docs, 3)
    arts = [str((d.metadata or {}).get("article_number")) for d in out]
    assert arts == ["3", "33", "213.3"]


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
