"""Tests for tabular cell RAG pipeline (recall → rerank → single LLM)."""

import pytest
from types import SimpleNamespace

from app.services.tabular_review_models import TabularCellExtractionModel, coerce_optional_int
from app.services.tabular_cell_pipeline import (
    _tabular_cell_budget_profile,
    augment_context_for_column,
    build_extraction_prompt,
    build_retrieval_query,
    cell_retrieval_params_from_models,
    column_type_description,
    tabular_final_k,
    enrich_source_from_documents,
    cell_result_to_api_payload,
    cell_result_to_websocket_payload,
    rerank_for_cell,
    TabularColumnExtractionOutcome,
)
from langchain_core.documents import Document


def test_coerce_optional_int_handles_llm_placeholders():
    assert coerce_optional_int("N/A") is None
    assert coerce_optional_int("стр. 3") == 3


def test_tabular_extraction_model_accepts_na_source_page():
    model = TabularCellExtractionModel(
        cell_value="Договор",
        source_page="N/A",
        reasoning="test",
        column_type="text",
    )
    assert model.source_page is None


def test_build_retrieval_query_uses_column_prompt_only():
    col = SimpleNamespace(prompt="Какая дата?", column_label="Дата", column_type="text")
    assert build_retrieval_query(col) == "Какая дата?"


def test_build_retrieval_query_falls_back_to_label():
    col = SimpleNamespace(prompt="", column_label="Дата", column_type="text")
    assert build_retrieval_query(col) == "Дата"


def test_build_retrieval_query_adds_type_hints_for_date():
    col = SimpleNamespace(
        prompt="Дата подписания договора",
        column_label="Дата",
        column_type="date",
    )
    query = build_retrieval_query(col)
    assert query.startswith("Дата подписания договора")
    assert "шапка" in query


def test_augment_context_for_date_prepends_document_header():
    body = "x" * 200
    header = "ШАПКА ДОКУМЕНТА от 15.05.2026" + (" " * 100)
    original = header + body
    context = "релевантный фрагмент без шапки"
    merged = augment_context_for_column(
        context,
        column_type="date",
        original_text=original,
    )
    assert "ШАПКА ДОКУМЕНТА" in merged
    assert context in merged


def test_tabular_cell_budget_uses_single_file_tabular_knobs(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_cell_pipeline.config.TABULAR_RECALL_K",
        25,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.tabular_cell_pipeline.config.TABULAR_FINAL_K_SIMPLE",
        4,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.tabular_cell_pipeline.config.TABULAR_CONTEXT_MAX_CHARS",
        8000,
        raising=False,
    )
    budget = _tabular_cell_budget_profile("date")
    assert budget["final_k"] == 4
    assert budget["recall_k"] == 25
    assert budget["max_context_chars"] == 8000
    assert budget["rerank_enabled"] is False
    assert budget["skip_micro_recall_cap"] is True
    assert budget["parent_context_enabled"] is False

    monkeypatch.setattr(
        "app.services.tabular_cell_pipeline.config.TABULAR_RERANK_ENABLED",
        True,
        raising=False,
    )
    assert _tabular_cell_budget_profile("date")["rerank_enabled"] is True


def test_build_extraction_prompt_has_no_extra_template_variables():
    col = SimpleNamespace(
        column_type="verbatim",
        column_label="Дата",
        prompt="Какая дата подписания?",
        column_config=None,
    )
    prompt = build_extraction_prompt(col)
    assert set(prompt.input_variables) == {"question", "context", "column_type"}


def test_cell_retrieval_params_snapshot_orm_fields():
    file = SimpleNamespace(
        case_id="case-1",
        id="file-1",
        filename="doc.pdf",
        original_text="текст",
    )
    col = SimpleNamespace(
        prompt="вопрос",
        column_label="Колонка",
        column_type="text",
    )
    params = cell_retrieval_params_from_models(file, col)
    assert params.case_id == "case-1"
    assert params.file_id == "file-1"
    assert params.column_type == "text"
    assert "вопрос" in params.query


def test_doc_belongs_to_file_scopes_by_metadata():
    from app.services.tabular_cell_pipeline import doc_belongs_to_file

    fid = "file-abc"
    assert doc_belongs_to_file(
        Document(page_content="x", metadata={"file_id": fid}),
        fid,
    )
    assert not doc_belongs_to_file(
        Document(page_content="x", metadata={"file_id": "other"}),
        fid,
    )


def test_tabular_final_k_simple_vs_text():
    assert tabular_final_k("date") <= tabular_final_k("text")


def test_enrich_source_from_top_chunk():
    result = TabularCellExtractionModel(
        cell_value="X",
        reasoning="r",
        column_type="text",
    )
    docs = [
        Document(page_content="text", metadata={"source_page": 2, "source_section": "§1"}),
    ]
    enriched = enrich_source_from_documents(result, docs)
    assert enriched.source_page == 2
    assert enriched.source_section == "§1"


def test_tabular_rerank_disabled_uses_hybrid_scores(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_cell_pipeline.config.TABULAR_RERANK_ENABLED",
        False,
        raising=False,
    )
    docs = [
        Document(page_content="low", metadata={"combined_score": 0.1}),
        Document(page_content="high", metadata={"combined_score": 0.9}),
        Document(page_content="mid", metadata={"combined_score": 0.5}),
    ]
    ranked = rerank_for_cell("query", docs, "text")
    assert len(ranked) <= tabular_final_k("text")
    assert ranked[0].page_content == "high"


def test_cell_result_to_websocket_payload_includes_cell_id():
    payload = cell_result_to_websocket_payload(
        "cell-uuid",
        {
            "file_id": "f1",
            "column_id": "c1",
            "cell_value": "X",
            "status": "completed",
        },
    )
    assert payload["cell_id"] == "cell-uuid"
    assert payload["file_id"] == "f1"


def test_tabular_column_extraction_outcome_succeeded():
    ok = TabularColumnExtractionOutcome.from_result(
        "f1",
        {"file_id": "f1", "column_id": "c1", "cell_value": "x"},
    )
    assert ok.succeeded
    err = TabularColumnExtractionOutcome.from_result("f1", {"error": "No text content"})
    assert not err.succeeded
    assert err.error == "No text content"
    exc = TabularColumnExtractionOutcome.from_exception("f1", RuntimeError("boom"))
    assert not exc.succeeded
    assert exc.error == "boom"


def test_cell_result_to_api_payload_shapes_run_response():
    payload = cell_result_to_api_payload(
        {
            "file_id": "f1",
            "column_id": "c1",
            "cell_value": "Договор",
            "normalized_value": "договор",
            "verbatim_extract": "Договор поставки",
            "reasoning": "найдено в шапке",
            "confidence_score": 0.92,
            "source_page": 1,
            "source_section": "§1",
            "source_references": [{"page": 1, "section": "§1"}],
            "status": "completed",
            "candidates": None,
            "extraction_method": "structured",
        }
    )
    assert payload["file_id"] == "f1"
    assert payload["column_id"] == "c1"
    assert payload["cell_value"] == "Договор"
    assert payload["status"] == "completed"
    assert "extraction_method" not in payload
