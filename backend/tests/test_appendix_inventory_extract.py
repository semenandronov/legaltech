"""Tests for appendix inventory authority + target-anchored cross-ref follow."""
from __future__ import annotations

from types import SimpleNamespace

from langchain_core.documents import Document

from app.services.appendix_inventory_extract import (
    column_requires_appendix_inventory,
    extract_inventory_items,
    format_inventory_cell_value,
    try_inventory_extraction_from_docs,
)
from app.services.file_document_outline import OutlineSectionEntry
from app.services.tabular_cross_ref_enrich import (
    enrich_docs_with_cross_references,
    extract_clause_body,
    order_docs_for_prompt,
)
from app.services.tabular_document_context import TabularFileContextPackage


SPEC_BLOB = """
Приложение № 1 к Договору аренды движимого имущества
СПЕЦИФИКАЦИЯ № 1
1. Арендодатель передает в аренду, а Арендатор принимает следующее Имущество
Электросамокат E-Scooter Mk087 50 37 000 1 850 000
2 Зарядное устройство для электросамоката E-Scooter Mk087 50 3 000 150 000
Итого: 2 000 000
"""

SECTION7_BLOB = """
Раздел 7. Ответственность Сторон
7.7. Риск гибели и повреждения Имущества лежит на Арендаторе.
7.8. В случае утраты Арендатором Имущества или его части, Арендатор возмещает Арендодателю стоимость утраченного Имущества исходя из стоимости Имущества, указанной в Приложении №1 к настоящему Договору в течение 5 банковских дней с даты окончания срока аренды.
7.9. За нарушение п. 4.2.2. Договора Арендатор выплачивает Арендодателю штраф в размере стоимости (указанной в Спецификации) Имущества, которое пришло в нерабочее состояние и/или не используется Арендатором.
"""


def test_extract_inventory_scooter_and_charger():
    items = extract_inventory_items(SPEC_BLOB)
    assert len(items) >= 2
    names = " ".join(n.lower() for n, _ in items)
    assert "электросамокат" in names
    assert "зарядн" in names
    assert any(q == 50 for _, q in items)
    value = format_inventory_cell_value(items)
    assert "50 шт." in value
    assert "Зарядн" in value or "зарядн" in value.lower()


def test_column_requires_inventory_for_object_prompt():
    col = SimpleNamespace(
        column_label="Объект аренды",
        prompt="Какой Объект аренды?",
        column_config={},
    )
    assert column_requires_appendix_inventory(col) is True


def test_try_inventory_from_followed_docs():
    docs = [
        Document(
            page_content=SPEC_BLOB,
            metadata={
                "cross_ref_followed": True,
                "cross_ref_required": True,
                "section_title": "Приложение № 1",
                "file_id": "f1",
            },
        )
    ]
    extraction = try_inventory_extraction_from_docs(docs)
    assert extraction is not None
    assert "электросамокат" in extraction.cell_value.lower()
    assert "зарядн" in extraction.cell_value.lower()
    assert extraction.extraction_method == "appendix_inventory"


def test_extract_clause_body_isolates_7_9_from_7_8():
    body = extract_clause_body(SECTION7_BLOB, "7.9")
    assert "7.9." in body
    assert "штраф" in body.lower()
    assert "Приложении №1" not in body
    assert "7.8." not in body


def test_exact_clause_does_not_follow_neighbor_appendix(monkeypatch):
    """Asking 7.9 must NOT hard-follow Appendix from neighboring 7.8."""
    monkeypatch.setattr(
        "app.services.tabular_cross_ref_enrich.tabular_cross_ref_follow_enabled",
        lambda: True,
    )
    outline = (
        OutlineSectionEntry(
            "sr7", "Раздел 7. Ответственность Сторон", "7", 1000, 2000, "Раздел 7", "body", ""
        ),
        OutlineSectionEntry(
            "sr_app1",
            "Приложение № 1 к Договору аренды движимого имущества",
            "",
            2000,
            5000,
            "Приложение № 1",
            "appendix",
            "1",
        ),
    )
    pkg = TabularFileContextPackage(
        file_id="f1",
        outline=outline,
        passport_blurb="",
        definition_section_roots=(),
        index_fingerprint="t",
    )
    docs = [
        Document(
            page_content=SECTION7_BLOB,
            metadata={"file_id": "f1", "section_root_id": "sr7", "chunk_id": "s7"},
        )
    ]

    class _VS:
        def fetch_macro_chunks_by_section_root_ids(self, case_id, section_ids):
            assert False, "must not fetch appendix when seed is only 7.9"

    merged, meta = enrich_docs_with_cross_references(
        docs,
        file_context=pkg,
        vector_store=_VS(),
        case_id="c1",
        file_id="f1",
        exact_query="7.9",
    )
    assert meta.get("follow_mode") == "exact_clause_target"
    assert meta.get("cross_ref_enrich") is False
    assert any((d.metadata or {}).get("query_target") for d in merged)
    assert not any((d.metadata or {}).get("cross_ref_followed") for d in merged)
    ordered = order_docs_for_prompt(merged)
    assert (ordered[0].metadata or {}).get("query_target") is True


def test_enrich_pins_appendix_for_subject_without_exact(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_cross_ref_enrich.tabular_cross_ref_follow_enabled",
        lambda: True,
    )
    outline = (
        OutlineSectionEntry("sr1", "1. Предмет Договора", "1", 0, 500, "1. Предмет", "body", ""),
        OutlineSectionEntry(
            "sr_app1",
            "Приложение № 1 к Договору аренды движимого имущества",
            "",
            2000,
            5000,
            "Приложение № 1",
            "appendix",
            "1",
        ),
    )
    pkg = TabularFileContextPackage(
        file_id="f1",
        outline=outline,
        passport_blurb="",
        definition_section_roots=(),
        index_fingerprint="t",
    )
    docs = [
        Document(
            page_content=(
                "1.2. Имуществом являются электросамокаты, количество, наименование, "
                "комплектация указаны в Приложении №1 к настоящему Договору, "
                "далее также именуемом как Спецификация №1."
            ),
            metadata={"file_id": "f1", "section_root_id": "sr1"},
        )
    ]

    class _VS:
        def fetch_macro_chunks_by_section_root_ids(self, case_id, section_ids):
            return {
                "sr_app1": [
                    Document(
                        page_content="Реквизиты Арендодателя р/с 40702 БИК 044525593 " * 5,
                        metadata={
                            "file_id": "f1",
                            "section_root_id": "sr_app1",
                            "chunk_id": "sig",
                            "char_start": 4000,
                        },
                    ),
                    Document(
                        page_content=SPEC_BLOB,
                        metadata={
                            "file_id": "f1",
                            "section_root_id": "sr_app1",
                            "chunk_id": "inv",
                            "char_start": 2100,
                        },
                    ),
                ]
            }

    merged, meta = enrich_docs_with_cross_references(
        docs, file_context=pkg, vector_store=_VS(), case_id="c1", file_id="f1"
    )
    assert meta.get("cross_ref_enrich") is True
    assert meta.get("follow_mode") == "bag_subject"
    assert meta.get("has_appendix_follow") is True
    assert any("Зарядное устройство" in (d.page_content or "") for d in merged)
