"""Тесты budgeted legal retrieval agent и resolve_legal_corpus_route."""

from __future__ import annotations

import time

from langchain_core.documents import Document

from app.config import config
from app.services.chat.legal_router import (
    article_suggests_fz127,
    extract_article_number,
    resolve_legal_corpus_route,
    route_legal_corpus_query,
)
from app.services.chat import legal_retrieval_agent as lra


def test_extract_article_number():
    assert extract_article_number("о чем статья 61") == "61"
    assert extract_article_number("ст. 61.2 127-ФЗ") == "61.2"


def test_article_suggests_fz127():
    assert article_suggests_fz127("61")
    assert article_suggests_fz127("61.2")
    assert not article_suggests_fz127("336")


def test_route_article_61_bankruptcy_markers():
    route = route_legal_corpus_query("о чем статья 61")
    assert "fz-127" in route.instrument_ids
    assert "plenum-63" not in route.instrument_ids


def test_resolve_legal_route_bare_article_with_legal_research():
    route = resolve_legal_corpus_route("о чем статья 61", legal_research=True)
    assert "fz-127" in route.instrument_ids


def test_resolve_legal_route_vacation_still_unknown():
    route = resolve_legal_corpus_route("Как оформить отпуск по ТК РФ?", legal_research=False)
    assert route.instrument_ids == ["unknown"]


def test_cap_search_queries():
    qs = lra._cap_search_queries("вопрос", ["q1", "q2", "q3", "q4"], max_queries=2)
    assert len(qs) == 2
    assert qs[0] == "вопрос"


def test_heuristic_sufficient_with_article():
    docs = [
        Document(
            page_content="Статья 61. Порядок оспаривания сделок должника " + "x" * 500,
            metadata={"section_title": "Статья 61"},
        )
    ]
    assert lra._heuristic_sufficient(docs, article="61")


def test_run_legal_corpus_fast_path(monkeypatch):
    from app.services.chat.legal_query_plan import LegalRetrievalPlan

    fast_docs = [
        Document(
            page_content="Статья 61 " + "текст " * 80,
            metadata={
                "source_filename": "127.pdf",
                "section_title": "Статья 61",
                "article_number": "61",
                "clause_ref": "1",
            },
        ),
        Document(
            page_content="2. Второй пункт " + "текст " * 80,
            metadata={
                "source_filename": "127.pdf",
                "article_number": "61",
                "clause_ref": "2",
            },
        ),
    ]
    lookup_plan = LegalRetrievalPlan(
        topic="article_lookup",
        required_articles=["61"],
        instrument_ids=["fz-127"],
        search_queries=["о чем статья 61"],
        rationale="test",
        user_articles=["61"],
    )
    monkeypatch.setattr(
        lra,
        "resolve_legal_retrieval_plan",
        lambda *a, **k: (lookup_plan, "deterministic"),
    )
    monkeypatch.setattr(
        lra,
        "_fetch_norm_tree_for_plan",
        lambda plan, *, reference_date: ([], False),
    )
    monkeypatch.setattr(
        lra,
        "_fetch_required_articles_fast",
        lambda plan, question, *, k: (fast_docs, True),
    )
    monkeypatch.setattr(lra, "_maybe_plenum_supplement", lambda docs, *a, **k: docs)
    hybrid_called = []

    def _hybrid_guard(*a, **k):
        hybrid_called.append(1)
        return []

    monkeypatch.setattr(
        "app.services.legal_corpus_service.retrieve_legal_corpus_documents",
        _hybrid_guard,
    )

    result = lra.run_legal_corpus_retrieval(
        "о чем статья 61",
        k=4,
        max_chars=8000,
        legal_research=True,
        include_iterative=False,
    )
    assert result.used_fast_path
    assert result.context
    assert result.documents
    assert "fz-127" in result.instrument_ids
    assert not hybrid_called


def test_retrieve_without_original_query_in_hybrid_pool(monkeypatch):
    from app.services import legal_corpus_service as lcs

    monkeypatch.setattr(lcs, "should_skip_retrieval_for_message", lambda _q: False)
    monkeypatch.setattr(lcs, "count_corpus_chunks", lambda: 1)
    monkeypatch.setattr(config, "LEGAL_CORPUS_USE_RERANKER", False, raising=False)
    calls = []

    def _fake_hybrid(q, k, instrument_ids=None):
        calls.append(q)
        return [Document(page_content=f"hit-{q}", metadata={"chunk_id": q})]

    monkeypatch.setattr(lcs, "_run_norm_hybrid_search", _fake_hybrid)
    monkeypatch.setattr(lcs, "_run_fts_bm25_search", lambda *a, **k: [])
    monkeypatch.setattr(lcs, "_run_lexical_search", lambda *a, **k: [])

    long_q = "Какой минимальный размер совокупных требований " + "установлен " * 20
    lcs.retrieve_legal_corpus_documents(
        long_q,
        k=2,
        search_queries=["короткий запрос банкротство юрлицо"],
        max_search_queries=1,
        include_original_query=False,
    )
    assert len(calls) == 1
    assert calls[0] == "короткий запрос банкротство юрлицо"
    assert long_q not in calls


def test_cap_search_queries_from_plan_skips_full_question():
    from app.services.chat.legal_query_plan import LegalRetrievalPlan

    plan = LegalRetrievalPlan(
        topic="general_bankruptcy",
        required_articles=[],
        instrument_ids=["fz-127"],
        search_queries=["порог банкротства юрлицо", "период просрочки"],
        rationale="test",
        facts=["минимальный размер требований"],
    )
    long_q = "очень длинный вопрос " * 30
    qs = lra._cap_search_queries_from_plan(plan, long_q)
    assert long_q not in qs
    assert qs[0] == "порог банкротства юрлицо"


def test_retrieve_hybrid_queries_run_in_parallel(monkeypatch):
    from app.services import legal_corpus_service as lcs

    monkeypatch.setattr(lcs, "should_skip_retrieval_for_message", lambda _q: False)
    monkeypatch.setattr(lcs, "count_corpus_chunks", lambda: 1)
    monkeypatch.setattr(config, "LEGAL_CORPUS_USE_RERANKER", False, raising=False)
    monkeypatch.setattr(config, "LEGAL_CORPUS_HYBRID_PARALLEL", True, raising=False)
    monkeypatch.setattr(config, "LEGAL_CORPUS_HYBRID_MAX_WORKERS", 4, raising=False)

    import threading

    lock = threading.Lock()
    active = {"n": 0, "max": 0}

    def _fake_hybrid(q, k, instrument_ids=None):
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        try:
            time.sleep(0.05)
            return [Document(page_content=f"hit-{q}", metadata={"chunk_id": q})]
        finally:
            with lock:
                active["n"] -= 1

    monkeypatch.setattr(lcs, "_run_norm_hybrid_search", _fake_hybrid)
    monkeypatch.setattr(lcs, "_run_fts_bm25_search", lambda *a, **k: [])
    monkeypatch.setattr(lcs, "_run_lexical_search", lambda *a, **k: [])

    lcs.retrieve_legal_corpus_documents(
        "тест",
        k=2,
        search_queries=["q1", "q2", "q3"],
        max_search_queries=3,
        include_original_query=False,
    )
    assert active["max"] >= 2


def test_retrieve_max_search_queries_cap(monkeypatch):
    from app.services import legal_corpus_service as lcs

    monkeypatch.setattr(lcs, "should_skip_retrieval_for_message", lambda _q: False)
    monkeypatch.setattr(lcs, "count_corpus_chunks", lambda: 1)
    monkeypatch.setattr(config, "LEGAL_CORPUS_USE_RERANKER", False, raising=False)
    calls = []

    def _fake_hybrid(q, k, instrument_ids=None):
        calls.append(q)
        return [Document(page_content=f"hit-{q}", metadata={"chunk_id": q})]

    monkeypatch.setattr(lcs, "_run_norm_hybrid_search", _fake_hybrid)
    monkeypatch.setattr(lcs, "_run_fts_bm25_search", lambda *a, **k: [])
    monkeypatch.setattr(lcs, "_run_lexical_search", lambda *a, **k: [])

    out = lcs.retrieve_legal_corpus_documents(
        "тест",
        k=2,
        search_queries=["q1", "q2", "q3", "q4"],
        max_search_queries=2,
    )
    assert len(calls) == 2
    assert len(out) <= 2


def test_skip_rerank_on_fast_path_sufficient():
    from app.services.chat.legal_query_plan import LegalRetrievalPlan

    plan = LegalRetrievalPlan(
        topic="article_lookup",
        required_articles=["61.2"],
        user_articles=["61.2"],
        instrument_ids=["fz-127"],
        search_queries=[],
        rationale="test",
    )
    docs = [
        Document(
            page_content="Статья 61.2 " + "x" * 500,
            metadata={"section_title": "Статья 61.2", "article_number": "61.2", "clause_ref": "1"},
        )
    ]
    assert lra._skip_rerank_on_fast_path(True, docs, plan) is True


def test_maybe_rerank_respects_skip_flag(monkeypatch):
    from app.services import legal_corpus_service as lcs

    monkeypatch.setattr(config, "LEGAL_CORPUS_USE_RERANKER", True, raising=False)
    rerank_called = []

    class _FakeSvc:
        def rerank(self, *a, **k):
            rerank_called.append(1)
            return a[1]

    monkeypatch.setattr(
        "app.services.reranker_service.get_reranker_for_tier",
        lambda _tier: _FakeSvc(),
    )
    docs = [Document(page_content="a", metadata={})]
    out = lcs._maybe_rerank_legal_pool("q", docs, top_k=1, skip_rerank=True)
    assert len(out) == 1
    assert not rerank_called
