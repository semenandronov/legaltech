"""Rank-gap rerank skip and rerank tier selection."""
from langchain_core.documents import Document

from app.services.chat.case_context_pipeline import (
    _recall_rank_gap_sufficient,
    rerank_case_documents,
)


def test_rank_gap_sufficient_when_head_separates():
    docs = [
        Document(page_content="a", metadata={"combined_score": 0.95}),
        Document(page_content="b", metadata={"combined_score": 0.94}),
        Document(page_content="c", metadata={"combined_score": 0.20}),
        Document(page_content="d", metadata={"combined_score": 0.15}),
    ]
    assert _recall_rank_gap_sufficient(docs, final_k=2) is True


def test_rank_gap_not_sufficient_when_flat():
    docs = [
        Document(page_content=f"x{i}", metadata={"combined_score": 0.5 + i * 0.01})
        for i in range(6)
    ]
    assert _recall_rank_gap_sufficient(docs, final_k=2) is False


def test_rerank_skipped_on_rank_gap(monkeypatch):
    monkeypatch.setenv("CASE_ASSISTANT_SKIP_RERANK_WHEN_SUFFICIENT", "true")
    from app.config import config

    config.CASE_ASSISTANT_SKIP_RERANK_WHEN_SUFFICIENT = True
    config.CASE_ASSISTANT_SKIP_RERANK_MIN_RANK_GAP = 0.12

    docs = [
        Document(page_content="a", metadata={"combined_score": 0.95}),
        Document(page_content="b", metadata={"combined_score": 0.93}),
        Document(page_content="c", metadata={"combined_score": 0.10}),
    ]
    out = rerank_case_documents(
        question="срок оплаты",
        docs=docs,
        final_k=2,
        budget_profile={"rerank_enabled": True, "rerank_tier": "light"},
    )
    assert len(out) == 2
