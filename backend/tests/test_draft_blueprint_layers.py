"""Tests for Blueprint Layer 1: task decomposition and triage."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.draft_pipeline.nodes.consolidate_state import consolidate_extractions
from app.services.draft_pipeline.nodes.document_triage import triage_case_documents
from app.services.draft_pipeline.nodes.task_decomposer import _heuristic_plan, decompose_draft_task
from app.services.draft_pipeline.schemas import (
    DocumentExtractionRecord,
    DocumentTriageResult,
    DraftTaskPlan,
    TriagedFile,
)


def test_heuristic_plan_supply_debt():
    plan = _heuristic_plan("составь иск о взыскании задолженности по договору поставки")
    assert plan.target_document_type
    assert len(plan.sub_queries) >= 3
    roles = {sq.role for sq in plan.sub_queries}
    assert "contract" in roles
    assert "payment_order" in roles


def test_decompose_fallback_without_llm():
    plan = decompose_draft_task("")
    assert plan.source == "empty"


def test_triage_picks_core_files():
    from app.services.chat.retrieval_router import CaseFileCatalogEntry

    catalog = [
        CaseFileCatalogEntry(
            file_id="f1",
            filename="Договор поставки.pdf",
            doc_type="contract",
            summary="договор между сторонами",
        ),
        CaseFileCatalogEntry(
            file_id="f2",
            filename="Акт.pdf",
            doc_type="act",
            summary="акт приема передачи",
        ),
    ]
    plan = _heuristic_plan("иск о задолженности по поставке")

    with patch(
        "app.services.draft_pipeline.nodes.document_triage.build_case_file_catalog",
        return_value=catalog,
    ):
        triage = triage_case_documents(
            db=MagicMock(),
            case_id="case-1",
            task_plan=plan,
        )

    assert isinstance(triage, DocumentTriageResult)
    assert triage.core_file_ids
    assert "f1" in triage.core_file_ids or "f2" in triage.core_file_ids


def test_triage_russian_doc_type_maps_to_contract_role():
    """Regression: catalog doc_type 'договор' must not fall through to act role."""
    from app.services.chat.retrieval_router import CaseFileCatalogEntry

    catalog = [
        CaseFileCatalogEntry(
            file_id="contract-ru",
            filename="Договор поставки.pdf",
            doc_type="договор",
            summary="договор поставки между сторонами",
        ),
        CaseFileCatalogEntry(
            file_id="act-ru",
            filename="Акт приема-передачи.pdf",
            doc_type="акт",
            summary="акт приема передачи оборудования",
        ),
        CaseFileCatalogEntry(
            file_id="pay-ru",
            filename="Платежное поручение.pdf",
            doc_type="other",
            summary="платежное поручение частичная оплата",
        ),
    ]
    plan = DraftTaskPlan(
        target_document_type="исковое заявление",
        required_doc_roles=["contract", "primary_execution_act", "payment_order"],
    )
    with patch(
        "app.services.draft_pipeline.nodes.document_triage.build_case_file_catalog",
        return_value=catalog,
    ):
        triage = triage_case_documents(db=MagicMock(), case_id="case-ru", task_plan=plan)

    roles_by_file = {f.file_id: f.role for f in triage.core_files}
    assert roles_by_file["contract-ru"] == "contract"
    assert roles_by_file["act-ru"] == "primary_execution_act"
    assert roles_by_file["pay-ru"] == "payment_order"


def test_consolidate_merges_contract_and_payment():
    plan = DraftTaskPlan(target_document_type="исковое заявление")
    records = [
        DocumentExtractionRecord(
            file_id="f1",
            schema_name="ContractExtraction",
            role="contract",
            payload={
                "contract_date": "2025-06-01",
                "total_price": "4500000",
                "payment_term_days": 10,
                "payment_term_unit": "business_days",
                "penalty_rate_percent_per_day": "0.1",
                "parties": {"поставщик": "ООО А", "покупатель": "ООО Б"},
            },
        ),
        DocumentExtractionRecord(
            file_id="f2",
            schema_name="ActExtraction",
            role="primary_execution_act",
            payload={"act_date": "2025-06-02", "amount": "4500000"},
        ),
        DocumentExtractionRecord(
            file_id="f3",
            schema_name="PaymentExtraction",
            role="payment_order",
            payload={"payment_date": "2025-06-25", "amount": "1500000", "document_number": "112"},
        ),
    ]
    facts = consolidate_extractions(records=records, task_plan=plan, user_prompt="иск")
    assert facts.dates.get("дата акта") == "2025-06-02"
    assert len(facts.financial.partial_payments) == 1
    assert facts.penalty_terms is not None
    assert facts.penalty_terms.payment_term_value == 10


def test_consolidate_keeps_penalty_terms_with_rate_and_principal_only():
    plan = DraftTaskPlan(target_document_type="исковое заявление")
    records = [
        DocumentExtractionRecord(
            file_id="f1",
            schema_name="ContractExtraction",
            role="contract",
            payload={
                "total_price": "4 500 000 руб.",
                "payment_term_days": 10,
                "payment_term_unit": "business_days",
                "penalty_rate_percent_per_day": "0.1",
            },
        ),
    ]
    facts = consolidate_extractions(
        records=records,
        task_plan=plan,
        user_prompt="иск по состоянию на 2026-06-07",
    )
    assert facts.penalty_terms is not None
    assert facts.penalty_terms.penalty_rate_percent_per_day == "0.1"
    assert facts.penalty_terms.penalty_end_date == "2026-06-07"
