"""Tests for chunk file passport inference and prompt headers."""
from langchain_core.documents import Document

from app.services.chat.chunk_file_passport import (
    attach_passports_to_source_headers,
    infer_file_identity_bundle,
    passport_for_document,
)
from app.services.rag_service import RAGService


def test_infer_passport_merges_contract_no_from_sibling_chunk():
    header = Document(
        page_content="ДОГОВОР ПОСТАВКИ №54\n16 апреля 2024\nг. Москва",
        metadata={
            "file_id": "f04",
            "source_file": "04. договор от 16.04.2024 на 5л.pdf",
            "chunk_index": 0,
        },
    )
    clause = Document(
        page_content=(
            "3.1.1. Передать оборудование в течение 90 рабочих дней "
            "с момента оплаты аванса."
        ),
        metadata={
            "file_id": "f04",
            "source_file": "04. договор от 16.04.2024 на 5л.pdf",
            "chunk_index": 16,
        },
    )
    identities = infer_file_identity_bundle([clause, header])
    line = passport_for_document(clause, identities=identities)
    assert "№54" in line
    assert "04. договор" in line
    assert "Паспорт:" in line


def test_infer_passport_uses_doc_summary_short():
    doc = Document(
        page_content="2.1. Стоимость оборудования составляет-3 400 000 рублей.",
        metadata={
            "file_id": "f05",
            "source_file": "05. договор от 02.02.2024 на 5л.pdf",
            "doc_summary_short": (
                "Договор поставки №51 от 02.02.2024 между ООО «Технион Групп» "
                "и ИП Кочкин О.Н."
            ),
        },
    )
    line = passport_for_document(
        doc, identities=infer_file_identity_bundle([doc])
    )
    assert "№51" in line
    assert "02.02.2024" in line or "02.02.2024" in line.replace("/", ".")


def test_format_sources_includes_passport_line():
    svc = object.__new__(RAGService)
    docs = [
        Document(
            page_content="ДОГОВОР ПОСТАВКИ №54\nусловия",
            metadata={"source_file": "04. договор от 16.04.2024 на 5л.pdf", "file_id": "a"},
        ),
        Document(
            page_content="в течение 90 рабочих дней",
            metadata={"source_file": "04. договор от 16.04.2024 на 5л.pdf", "file_id": "a"},
        ),
    ]
    text, included = RAGService.format_sources_for_prompt_with_docs(
        svc, docs, max_context_chars=8000
    )
    assert len(included) == 2
    assert "Паспорт:" in text
    assert "№54" in text
    assert text.count("Паспорт:") >= 2
