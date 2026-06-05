"""Tests for context ceiling, rerank short-circuit, micro recall default."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.services.chat.case_context_pipeline import (
    max_assemble_context_chars,
    rerank_case_documents,
)


def test_max_assemble_context_chars_uses_env_ceiling(monkeypatch):
    monkeypatch.setattr("app.config.config.CASE_ASSISTANT_MAX_CONTEXT_CHARS_CEILING", 48_000)
    assert max_assemble_context_chars({"max_context_chars": 64_000}) == 48_000
    assert max_assemble_context_chars({"max_context_chars": 16_000}) == 16_000


def test_max_assemble_context_chars_default_when_no_budget(monkeypatch):
    monkeypatch.setattr("app.config.config.CASE_ASSISTANT_MAX_CONTEXT_CHARS_CEILING", 32_000)
    assert max_assemble_context_chars(None) == 4000


def test_rerank_short_circuit_when_pool_le_final_k():
    docs = [
        Document(page_content=f"chunk {i}", metadata={"file_id": f"f{i}"})
        for i in range(3)
    ]
    with patch("app.services.reranker_service.get_reranker_service") as mock_get:
        out = rerank_case_documents(
            question="о чем документы",
            docs=docs,
            final_k=10,
            budget_profile={"rerank_enabled": True},
        )
        mock_get.assert_not_called()
    assert len(out) == 3
    assert out[0].metadata.get("rerank_score") == 1.0
    assert out[1].metadata.get("rerank_score") == 0.99


def test_rerank_calls_model_when_pool_exceeds_final_k():
    docs = [Document(page_content=f"chunk {i}", metadata={}) for i in range(5)]
    mock_svc = MagicMock()
    proxies = []
    for i, d in enumerate(docs):
        md = dict(d.metadata or {})
        md["_rerank_ix"] = i
        proxies.append(Document(page_content=d.page_content, metadata=md))
    mock_svc.rerank.return_value = [(proxies[1], 0.9), (proxies[0], 0.5)]
    with patch(
        "app.services.reranker_service.get_reranker_service",
        return_value=mock_svc,
    ):
        out = rerank_case_documents(
            question="query",
            docs=docs,
            final_k=2,
            budget_profile={"rerank_enabled": True},
        )
    mock_svc.rerank.assert_called_once()
    assert len(out) == 2
    assert out[0].page_content == "chunk 1"
