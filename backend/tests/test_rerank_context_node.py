"""Tests for rerank_context_node (pipeline stage 3)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.services.langchain_agents.graphs.chat_graph import rerank_context_node


def _make_docs(n: int) -> list[dict]:
    return [
        {
            "page_content": f"chunk {i} contract penalty",
            "metadata": {"file_id": f"f{i}", "chunk_index": i},
        }
        for i in range(n)
    ]


@patch("app.services.chat.case_context_pipeline.pipeline_enabled", return_value=True)
def test_rerank_context_trims_50_to_15(_p):
    rag_service = MagicMock()
    rag_service.format_sources_for_prompt_with_docs.return_value = ("ctx", [])

    ranked_docs = [
        Document(page_content=f"chunk {i}", metadata={"file_id": f"f{i}"})
        for i in range(15)
    ]

    with patch(
        "app.services.chat.case_context_pipeline.rerank_and_resolve_documents",
        return_value=(ranked_docs, {"parents_resolved": 15}),
    ) as mock_rerank:
        with patch(
            "app.services.chat.case_context_pipeline.assemble_rag_output",
            return_value={
                "rag_context": "assembled",
                "rag_documents": _make_docs(15),
                "citations": [],
            },
        ) as mock_assemble:
            state = {
                "mode": "normal",
                "question": "неустойка",
                "case_id": "case-1",
                "rag_documents": _make_docs(50),
                "budget_profile": {"final_k": 15, "max_sources": 15},
            }
            out = rerank_context_node(state, rag_service=rag_service, db=None)

    mock_rerank.assert_called_once()
    assert mock_rerank.call_args.kwargs["final_k"] == 15
    mock_assemble.assert_called_once()
    assert out["rag_context"] == "assembled"
    assert len(out["rag_documents"]) == 15
    assert out["context_pipeline_meta"]["recall_docs"] == 50
    assert out["context_pipeline_meta"]["rerank_docs"] == 15


@patch("app.services.chat.case_context_pipeline.pipeline_enabled", return_value=False)
def test_rerank_context_skipped_when_pipeline_disabled(_p):
    state = {"mode": "normal", "rag_documents": _make_docs(10)}
    out = rerank_context_node(state, rag_service=MagicMock(), db=None)
    assert out == {}


@patch("app.services.chat.case_context_pipeline.pipeline_enabled", return_value=True)
def test_rerank_context_empty_docs_passthrough(_p):
    state = {"mode": "normal", "question": "q", "rag_documents": []}
    out = rerank_context_node(state, rag_service=MagicMock(), db=None)
    assert out == {}
