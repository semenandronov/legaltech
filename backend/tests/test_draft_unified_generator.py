"""Tests for unified draft generation (single-pass, assistant-parity)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.draft_pipeline.generation_mode import get_draft_generation_mode, is_unified_generation
from app.services.draft_pipeline.graph import _route_after_verify_financials
from app.services.draft_pipeline.nodes.unified_generator import (
    _build_system_prompt,
    _build_user_prompt,
    run_unified_draft_generation,
)
from app.services.draft_pipeline.schemas import ExtractedFacts, FinancialSummary, VerifiedCalculations


def test_generation_mode_defaults_unified(monkeypatch):
    monkeypatch.setattr("app.config.config.DRAFT_GENERATION_MODE", "unified")
    assert is_unified_generation()
    assert get_draft_generation_mode() == "unified"


def test_graph_routes_to_unified_after_verify(monkeypatch):
    monkeypatch.setattr("app.config.config.DRAFT_GENERATION_MODE", "unified")
    assert _route_after_verify_financials({}) == "generate_unified"


def test_graph_routes_to_decomposed_when_configured(monkeypatch):
    monkeypatch.setattr("app.config.config.DRAFT_GENERATION_MODE", "decomposed")
    assert _route_after_verify_financials({}) == "blueprint"


def test_scratch_prompt_includes_rag_and_facts():
    facts = ExtractedFacts(
        document_type="исковое заявление",
        parties={"истец": "ООО Альфа"},
    )
    user = _build_user_prompt(
        strategy="scratch",
        user_prompt="составь иск",
        facts=facts,
        rag_context="Договор поставки № 45",
        template_html=None,
        template_label=None,
    )
    assert "Договор поставки" in user
    assert "исковое заявление" in user
    assert "ПАСПОРТ ФАКТОВ" in user
    assert _build_system_prompt(strategy="scratch")


def test_template_prompt_includes_template_body():
    facts = ExtractedFacts(document_type="исковое заявление")
    html = "<section><h2>Шапка</h2><p>[суд]</p></section>"
    user = _build_user_prompt(
        strategy="template",
        user_prompt="иск",
        facts=facts,
        rag_context="ctx",
        template_html=html,
        template_label="Иск юриста",
    )
    assert "HTML-ШАБЛОН" in user
    assert html in user
    assert "сохрани структуру" in _build_system_prompt(strategy="template").lower() or "структуру" in _build_system_prompt(strategy="template")


@patch("app.services.draft_pipeline.nodes.unified_generator.create_legal_llm")
def test_run_unified_returns_stripped_html(mock_llm_factory):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content="```html\n<section><p>Иск</p></section>\n```"
    )
    mock_llm_factory.return_value = mock_llm

    facts = ExtractedFacts(
        document_type="иск",
        financial=FinancialSummary(
            verified=VerifiedCalculations(total_claim="1 000 000 руб."),
            total_to_claim="1 000 000 руб.",
        ),
    )
    html = run_unified_draft_generation(
        strategy="scratch",
        user_prompt="иск",
        facts=facts,
        rag_context="материалы",
    )
    assert "<section>" in html
    assert "```" not in html
    mock_llm.invoke.assert_called_once()


@pytest.mark.parametrize("mode", ["unified", "decomposed"])
def test_full_graph_respects_generation_mode(mode, monkeypatch):
    from unittest.mock import patch

    from app.services.draft_pipeline.graph import create_draft_pipeline_graph
    from app.services.draft_pipeline.schemas import (
        DocumentExtractionRecord,
        DocumentTriageResult,
        DraftTaskPlan,
        ExtractedFacts,
        FinancialSummary,
        TriagedFile,
        CaseRetrievalSnapshot,
    )

    monkeypatch.setattr("app.config.config.DRAFT_GENERATION_MODE", mode)
    monkeypatch.setattr("app.config.config.DRAFT_LINTER_ENABLED", False)

    facts = ExtractedFacts(
        document_type="исковое заявление",
        financial=FinancialSummary(total_to_claim="3 000 000 руб."),
    )

    with (
        patch(
            "app.services.draft_pipeline.nodes.task_decomposer.decompose_draft_task",
            return_value=DraftTaskPlan(target_document_type="иск", source="test"),
        ),
        patch(
            "app.services.draft_pipeline.nodes.document_triage.triage_case_documents",
            return_value=DocumentTriageResult(
                core_files=[TriagedFile(file_id="f1", filename="d.pdf", role="contract", tier="core_data")],
                sidebar_files=[],
            ),
        ),
        patch(
            "app.services.draft_pipeline.nodes.retrieve_materials.run_case_materials_retrieval",
            return_value=CaseRetrievalSnapshot(rag_context="договор и акт", scoped_file_ids=["f1"]),
        ),
        patch(
            "app.services.draft_pipeline.nodes.parallel_extract.run_parallel_extraction",
            return_value=[DocumentExtractionRecord(file_id="f1", schema_name="ContractExtraction", payload={})],
        ),
        patch(
            "app.services.draft_pipeline.nodes.consolidate_state.consolidate_extractions",
            return_value=facts,
        ),
        patch(
            "app.services.draft_pipeline.nodes.resolve_template.resolve_draft_template_context",
            return_value=("", None, None),
        ),
        patch(
            "app.services.draft_pipeline.nodes.unified_generator.run_unified_draft_generation",
            return_value="<section><p>unified doc</p></section>",
        ),
        patch(
            "app.services.draft_pipeline.nodes.generate_sections.run_parallel_section_generation",
            return_value={"header": "<section><p>decomposed</p></section>"},
        ),
        patch(
            "app.services.draft_pipeline.nodes.persist.run_persist",
            return_value={"id": f"doc-{mode}", "title": "Иск", "preview": "x"},
        ),
    ):
        result = create_draft_pipeline_graph(db=MagicMock()).invoke(
            {"case_id": "c1", "user_id": "u1", "user_prompt": "иск"}
        )

    assert result.get("document_created")
    assert result.get("generation_mode") == mode
