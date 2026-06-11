"""Tests for unified draft case retrieval (case assistant pipeline reuse)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.draft_pipeline.case_retrieval import retrieve_case_materials_for_draft
from app.services.draft_pipeline.schemas import CaseRetrievalSnapshot, DocumentTriageResult, DraftTaskPlan, RetrievalSubQuery, TriagedFile


def test_retrieve_case_materials_delegates_to_case_context_pipeline():
    mock_rag = MagicMock()
    pipeline_out = {
        "rag_context": "Акт от 02.06.2025…",
        "scoped_file_ids": ["file-a"],
        "retrieval_task": {"search_query": "иск", "scope_mode": "resolved", "file_ids": ["file-a"]},
        "context_pipeline_meta": {"pipeline": True, "recall_docs": 40, "rerank_docs": 12},
        "citations": [],
    }

    with patch(
        "app.services.draft_pipeline.case_retrieval.run_case_context_pipeline",
        return_value=pipeline_out,
    ) as mock_pipeline:
        snap = retrieve_case_materials_for_draft(
            rag_service=mock_rag,
            case_id="case-1",
            user_prompt="составь иск",
            db=MagicMock(),
            attached_file_ids=["file-a"],
            task_plan=DraftTaskPlan(
                target_document_type="иск",
                sub_queries=[
                    RetrievalSubQuery(query_id="q1", role="contract", search_query="договор")
                ],
            ),
            triage=DocumentTriageResult(
                core_files=[
                    TriagedFile(file_id="file-a", filename="d.pdf", role="contract", tier="core_data")
                ]
            ),
        )

    assert mock_pipeline.call_count >= 1
    call_kw = mock_pipeline.call_args.kwargs
    assert call_kw["case_id"] == "case-1"
    assert call_kw["question"] == "договор"
    assert call_kw["attached_file_ids"] == ["file-a"]
    budget = call_kw["budget_profile"]
    assert budget.get("execution_tier") == "deep"

    assert isinstance(snap, CaseRetrievalSnapshot)
    assert "Акт" in snap.rag_context
    assert snap.scoped_file_ids == ["file-a"]
