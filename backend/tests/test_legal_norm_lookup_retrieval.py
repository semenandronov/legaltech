"""Интеграционный тест norm tree fast path в retrieval agent."""

from __future__ import annotations

from langchain_core.documents import Document

from app.services.chat import legal_retrieval_agent as lra
from app.services.chat.legal_query_plan import LegalRetrievalPlan


def test_run_legal_corpus_norm_tree_path(monkeypatch):
    tree_docs = [
        Document(
            page_content="Статья 61. Заголовок",
            metadata={"article_number": "61", "clause_ref": "", "norm_node_key": "fz-127::art::61"},
        ),
        Document(
            page_content="1. Первый пункт " + "текст " * 40,
            metadata={"article_number": "61", "clause_ref": "1", "norm_node_key": "fz-127::art::61::clause::1"},
        ),
        Document(
            page_content="2. Второй пункт " + "текст " * 40,
            metadata={"article_number": "61", "clause_ref": "2", "norm_node_key": "fz-127::art::61::clause::2"},
        ),
        Document(
            page_content="3. Третий пункт " + "текст " * 40,
            metadata={"article_number": "61", "clause_ref": "3", "norm_node_key": "fz-127::art::61::clause::3"},
        ),
    ]
    lookup_plan = LegalRetrievalPlan(
        topic="article_lookup",
        required_articles=["61"],
        instrument_ids=["fz-127"],
        search_queries=["пункт 3 статьи 61"],
        rationale="test",
        user_articles=["61"],
        user_clause_ref="3",
    )
    monkeypatch.setattr(
        lra,
        "resolve_legal_retrieval_plan",
        lambda *a, **k: (lookup_plan, "llm"),
    )
    monkeypatch.setattr(
        lra,
        "_fetch_norm_tree_for_plan",
        lambda plan, *, reference_date: (tree_docs, True),
    )
    monkeypatch.setattr(lra, "_expand_with_norm_graph", lambda docs, **k: docs)
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
        "о чем пункт 3 статьи 61",
        k=8,
        max_chars=12000,
        legal_research=True,
        include_iterative=False,
    )
    assert result.used_fast_path
    assert len(result.documents) == 4
    assert result.meta.get("used_norm_tree") is True
    assert not hybrid_called
    assert any((d.metadata or {}).get("clause_ref") == "3" for d in result.documents)
