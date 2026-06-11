"""Integration test: agentic draft graph v5 with mocked I/O."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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

MOCK_FACTS = ExtractedFacts(
    document_type="исковое заявление",
    parties={"истец": "ООО Альфа", "ответчик": "ООО Бета"},
    amounts={"сумма договора": "3 000 000 руб."},
    financial=FinancialSummary(
        principal_claim="3 000 000 руб.",
        total_to_claim="3 000 000 руб.",
        confidence="high",
    ),
)

MOCK_PLAN = DraftTaskPlan(
    target_document_type="исковое заявление",
    required_doc_roles=["contract", "primary_execution_act"],
    sub_queries=[],
    source="test",
)

MOCK_TRIAGE = DocumentTriageResult(
    core_files=[TriagedFile(file_id="f1", filename="d.pdf", role="contract", tier="core_data")],
    sidebar_files=[],
)


@pytest.fixture(autouse=True)
def _pipeline_flags(monkeypatch):
    monkeypatch.setattr("app.config.config.DRAFT_GENERATION_MODE", "decomposed")
    monkeypatch.setattr("app.config.config.DRAFT_SCRATCH_LLM_BLUEPRINT", False)
    monkeypatch.setattr("app.config.config.DRAFT_LINTER_ENABLED", False)


def _mock_persist(**kwargs):
    return {
        "id": "doc-v5-1",
        "title": kwargs.get("title") or "Иск",
        "preview": (kwargs.get("final_html") or "")[:200],
    }


def test_full_graph_v5_end_to_end():
    sections_out = {"header": "<section><h2>Шапка</h2><p>АС Москвы</p></section>"}

    with (
        patch(
            "app.services.draft_pipeline.nodes.task_decomposer.decompose_draft_task",
            return_value=MOCK_PLAN,
        ),
        patch(
            "app.services.draft_pipeline.nodes.document_triage.triage_case_documents",
            return_value=MOCK_TRIAGE,
        ),
        patch(
            "app.services.draft_pipeline.nodes.retrieve_materials.run_case_materials_retrieval",
            return_value=CaseRetrievalSnapshot(rag_context="ctx", scoped_file_ids=["f1"]),
        ),
        patch(
            "app.services.draft_pipeline.nodes.parallel_extract.run_parallel_extraction",
            return_value=[
                DocumentExtractionRecord(file_id="f1", schema_name="ContractExtraction", payload={})
            ],
        ),
        patch(
            "app.services.draft_pipeline.nodes.consolidate_state.consolidate_extractions",
            return_value=MOCK_FACTS,
        ),
        patch(
            "app.services.draft_pipeline.nodes.resolve_template.resolve_draft_template_context",
            return_value=("", None, None),
        ),
        patch(
            "app.services.draft_pipeline.nodes.generate_sections.run_parallel_section_generation",
            return_value=sections_out,
        ),
        patch(
            "app.services.draft_pipeline.nodes.persist.run_persist",
            side_effect=_mock_persist,
        ),
    ):
        graph = create_draft_pipeline_graph(db=MagicMock())
        result = graph.invoke(
            {
                "case_id": "case-v5",
                "user_id": "user-v5",
                "user_prompt": "составь иск о взыскании 3 млн",
            }
        )

    assert result.get("document_created")
    assert result["document_created"]["id"] == "doc-v5-1"
    assert result.get("task_plan")
    assert result.get("triage")
    assert result.get("extraction_records") is not None
