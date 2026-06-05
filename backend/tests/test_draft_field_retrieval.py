"""Тесты per-field RAG (моки)."""
from unittest.mock import MagicMock, patch

from app.services.draft_template_schemas import TemplateFieldSpec
from app.services.draft_field_retrieval import retrieve_for_template_field


def test_retrieve_for_template_field_uses_pipeline():
    field = TemplateFieldSpec(
        field_id="ph_000",
        marker="[ИНН]",
        retrieval_query="ИНН кредитора заявителя",
        semantic_label="ИНН кредитора",
        what_to_find="ИНН",
    )
    rag = MagicMock()
    with patch("app.services.draft_field_retrieval.pipeline_enabled", return_value=True):
        with patch("app.services.draft_field_retrieval.create_case_retrieval_router") as mock_router:
            with patch("app.services.draft_field_retrieval.run_hybrid_recall") as mock_recall:
                with patch("app.services.draft_field_retrieval.rerank_and_resolve_documents") as mock_rerank:
                    with patch("app.services.draft_field_retrieval.assemble_rag_output") as mock_asm:
                        task = MagicMock()
                        task.search_query = "ИНН кредитора"
                        task.scope_mode = "full_case"
                        task.confidence = 0.9
                        mock_router.return_value.route.return_value = task
                        doc = MagicMock()
                        doc.page_content = "ИНН 7701234567"
                        mock_recall.return_value = ([doc], {"recall_docs": 1})
                        mock_rerank.return_value = ([doc], {"parents_resolved": 1})
                        mock_asm.return_value = {"rag_context": "ИНН 7701234567", "rag_documents": []}
                        ctx, _docs, meta = retrieve_for_template_field(
                            rag_service=rag,
                            case_id="case-1",
                            field=field,
                            db=MagicMock(),
                        )
    assert "7701234567" in ctx
    assert meta.get("pipeline") is True
    mock_recall.assert_called_once()
