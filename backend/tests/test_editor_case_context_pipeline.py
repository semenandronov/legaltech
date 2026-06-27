"""Editor enrich uses the same case context pipeline as the internal assistant."""
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.services.langchain_agents.graphs.nodes.editor_nodes import editor_enrich_case_context_node


@patch("app.services.chat.case_context_pipeline.run_case_context_pipeline")
def test_editor_enrich_skips_rag_for_local_edit(mock_pipeline):
    state = {
        "case_id": "case-1",
        "question": "Поменяй сумму неустойки на 150 000",
        "editor_mode_hint": "edit",
        "document_id": "doc-1",
    }
    result = editor_enrich_case_context_node(state, db=MagicMock(), rag_service=MagicMock())

    mock_pipeline.assert_not_called()
    assert result.get("context_pipeline_meta", {}).get("pipeline") == "editor_skip"


@patch("app.services.chat.case_context_pipeline.run_case_context_pipeline")
def test_editor_enrich_uses_case_context_pipeline(mock_pipeline):
    mock_pipeline.return_value = {
        "rag_context": "ctx",
        "citations": [{"file": "a.pdf", "file_id": "f1"}],
        "context_pipeline_meta": {
            "pipeline": True,
            "recall_docs": 80,
            "rerank_docs": 12,
            "scope_mode": "full_case",
        },
        "retrieval_task": {"search_query": "ИНН", "scope_mode": "full_case"},
    }
    rag = MagicMock()
    state = {
        "case_id": "case-1",
        "question": "Какой ИНН у ответчика?",
        "document_id": "doc-1",
        "corpus_size": 10,
    }
    result = editor_enrich_case_context_node(state, db=MagicMock(), rag_service=rag)

    mock_pipeline.assert_called_once()
    call_kw = mock_pipeline.call_args.kwargs
    assert call_kw["case_id"] == "case-1"
    assert call_kw["question"] == "Какой ИНН у ответчика?"
    assert call_kw["document_id"] == "doc-1"
    assert call_kw["rag_service"] is rag
    assert result["rag_context"] == "ctx"
    assert result["context_pipeline_meta"]["rerank_docs"] == 12


@patch("app.services.chat.case_context_pipeline.pipeline_enabled", return_value=True)
@patch("app.services.chat.case_context_pipeline.assemble_rag_output")
@patch("app.services.chat.case_context_pipeline.rerank_and_resolve_documents")
@patch("app.services.chat.case_context_pipeline.run_hybrid_recall")
@patch("app.services.chat.retrieval_router.create_case_retrieval_router")
def test_run_case_context_pipeline_hybrid_and_rerank(
    mock_router_factory,
    mock_recall,
    mock_rerank,
    mock_assemble,
    _pipeline_on,
):
    from app.services.chat.case_context_pipeline import run_case_context_pipeline
    from app.services.chat.retrieval_router import RetrievalTask

    task = RetrievalTask(
        search_query="ИНН ответчика",
        file_ids=[],
        scope_mode="full_case",
        confidence=0.9,
    )
    router = MagicMock()
    router.route.return_value = task
    mock_router_factory.return_value = router

    doc = Document(page_content="ИНН 7701234567", metadata={"file_id": "f1"})
    mock_recall.return_value = ([doc], {"scope_mode": "full_case", "recall_docs": 1})
    mock_rerank.side_effect = lambda **kwargs: ([doc], {"parents_resolved": 1})
    mock_assemble.return_value = {
        "rag_context": "formatted",
        "rag_documents": [],
        "citations": [{"file": "a.pdf"}],
    }

    rag = MagicMock()
    out = run_case_context_pipeline(
        rag_service=rag,
        case_id="case-1",
        question="Какой ИНН?",
        db=MagicMock(),
        document_id="doc-1",
    )

    mock_recall.assert_called_once()
    assert mock_recall.call_args.kwargs["retrieval_task"] is task
    mock_rerank.assert_called_once()
    assert out["rag_context"] == "formatted"
    assert out["context_pipeline_meta"]["pipeline"] is True
