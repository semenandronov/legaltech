"""Extended tests for draft pipeline v2 (passport, linter, scratch planner)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.draft_pipeline.case_retrieval import build_draft_retrieval_budget_profile
from app.services.draft_pipeline.schemas import CaseRetrievalSnapshot
from app.services.draft_pipeline.json_utils import parse_llm_json_object
from app.services.draft_pipeline.markers import find_gap_markers, gap_marker, html_tag_balance_ok
from app.services.draft_pipeline.nodes.compiler import compile_scratch_document, compile_template_document
from app.services.draft_pipeline.nodes.document_linter import run_document_linter
from app.services.draft_pipeline.nodes.scratch_planner import plan_scratch_blueprint
from app.services.draft_pipeline.schemas import (
    BlueprintSection,
    DraftPipelineMetadata,
    ExtractedFacts,
    FinancialSummary,
)
from app.services.draft_pipeline.section_registry import build_blueprint, parse_template_sections


SAMPLE_TEMPLATE = """
<article>
  <section><h2>Шапка</h2><p>[СУД]</p></section>
  <section><h2>Фабула</h2><p>[ФАКТЫ]</p></section>
</article>
"""


@pytest.fixture(autouse=True)
def _disable_llm_blueprint(monkeypatch):
    monkeypatch.setattr("app.config.config.DRAFT_SCRATCH_LLM_BLUEPRINT", False)
    monkeypatch.setattr("app.config.config.DRAFT_LINTER_ENABLED", False)


def test_gap_marker_format():
    m = gap_marker("ИНН должника")
    assert m == "[ИНН должника]"
    found = find_gap_markers(f"ИНН {m} указан")
    assert found and found[0][0] == "ИНН должника"


def test_parse_template_sections():
    sections = parse_template_sections(SAMPLE_TEMPLATE)
    assert len(sections) == 2
    assert sections[0].title == "Шапка"
    assert sections[1].section_id


def test_compile_template_replaces_sections():
    blueprint = parse_template_sections(SAMPLE_TEMPLATE)
    generated = {
        blueprint[0].section_id: "<section><h2>Шапка</h2><p>АС города Москвы</p></section>",
        blueprint[1].section_id: "<section><h2>Фабула</h2><p>Долг не погашен.</p></section>",
    }
    html = compile_template_document(SAMPLE_TEMPLATE, blueprint, generated)
    assert "АС города Москвы" in html
    assert "Долг не погашен" in html
    assert html_tag_balance_ok(html)


def test_compile_scratch_assembles_article():
    blueprint = build_blueprint(strategy="scratch", template_html=None, user_prompt="иск")
    generated = {b.section_id: f"<p>Текст {b.section_id}</p>" for b in blueprint}
    html = compile_scratch_document(blueprint, generated)
    assert "legal-draft" in html
    assert all(f"Текст {b.section_id}" in html for b in blueprint)


def test_extracted_facts_from_llm_dict():
    facts = ExtractedFacts.from_llm_dict(
        {
            "document_type": "заявление о включении",
            "parties": {"истец": "ООО Альфа"},
            "amounts": {"долг": "1000000"},
            "financial": {
                "principal_claim": "3 000 000 руб.",
                "partial_payments": [{"date": "01.01.2024", "amount": "500 000", "source": "п/п №1"}],
                "total_to_claim": "2 500 000 руб.",
                "computation_method": "3 000 000 − 500 000",
                "confidence": "high",
            },
        }
    )
    assert facts.parties["истец"] == "ООО Альфа"
    assert facts.document_type == "заявление о включении"
    assert facts.financial.confidence == "high"
    assert len(facts.financial.partial_payments) == 1
    assert facts.financial.partial_payments[0].amount == "500 000"


def test_financial_summary_defaults():
    fs = FinancialSummary.from_llm_dict(None)
    assert fs.confidence == "missing"
    assert fs.partial_payments == []


def test_draft_pipeline_metadata_v2():
    meta = DraftPipelineMetadata(
        strategy="template",
        template_id="rtk_claim_st71",
        generated_sections={"facts": "<p>x</p>"},
        blueprint=[{"section_id": "facts", "title": "Фабула"}],
    )
    assert meta.pipeline_version == "unified_v1"
    assert meta.generation_mode == "unified"
    wrapped = meta.to_document_metadata()
    restored = DraftPipelineMetadata.from_document_metadata(wrapped)
    assert restored is not None
    assert restored.template_id == "rtk_claim_st71"


def test_case_retrieval_snapshot_from_pipeline():
    raw = {
        "rag_context": "Договор поставки…",
        "scoped_file_ids": ["f1", "f2"],
        "retrieval_task": {"search_query": "иск", "scope_mode": "resolved"},
        "context_pipeline_meta": {"pipeline": True, "final_k": 15},
        "citations": [{"file_id": "f1"}],
    }
    snap = CaseRetrievalSnapshot.from_pipeline_result(raw)
    assert "Договор" in snap.rag_context
    assert snap.scoped_file_ids == ["f1", "f2"]
    assert snap.context_pipeline_meta.get("pipeline") is True


def test_draft_retrieval_budget_uses_deep_tier():
    profile = build_draft_retrieval_budget_profile(
        user_prompt="составь иск о взыскании задолженности",
        corpus_size=10,
        attached_files_count=2,
    )
    assert profile.get("execution_tier") == "deep"
    assert int(profile.get("recall_k") or 0) > 0
    assert int(profile.get("final_k") or 0) > 0


def test_parse_llm_json_object_embedded():
    raw = 'Вот JSON:\n{"document_type": "иск", "parties": {}}'
    parsed = parse_llm_json_object(raw)
    assert parsed and parsed.get("document_type") == "иск"


def test_plan_scratch_blueprint_fallback():
    sections = plan_scratch_blueprint(
        user_prompt="подготовь иск о взыскании",
        facts=ExtractedFacts(document_type="исковое заявление"),
    )
    assert len(sections) >= 3
    assert all(isinstance(s, BlueprintSection) for s in sections)


def test_linter_preserves_gaps_when_disabled():
    html = "<section><p>Долг [сумма]</p></section>"
    facts = ExtractedFacts(amounts={"долг": "3000000"})
    out = run_document_linter(html=html, facts=facts, user_prompt="иск")
    assert out == html


def test_linter_rejects_bad_output(monkeypatch):
    monkeypatch.setattr("app.config.config.DRAFT_LINTER_ENABLED", True)
    html = "<section><p>Долг 3 000 000 руб. [ИНН]</p></section>"
    facts = ExtractedFacts(amounts={"долг": "3000000"})

    bad_llm = MagicMock()
    bad_llm.invoke.return_value = MagicMock(content="<section><p>Долг изменён</p></section>")

    with patch("app.services.draft_pipeline.nodes.document_linter.create_legal_llm", return_value=bad_llm):
        out = run_document_linter(html=html, facts=facts, user_prompt="иск")

    assert out == html
