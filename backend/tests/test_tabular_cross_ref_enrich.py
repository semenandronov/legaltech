"""Production tests for in-document cross-ref + appendix resolve."""
from __future__ import annotations

from langchain_core.documents import Document

from app.services.contract_cross_ref_resolve import (
    ContractRefTarget,
    collect_follow_section_ids,
    parse_contract_cross_references,
    resolve_ref_to_section_root_ids,
)
from app.services.file_document_outline import (
    OutlineSectionEntry,
    build_outline_from_chunks,
)
from app.services.tabular_cross_ref_enrich import enrich_docs_with_cross_references
from app.services.tabular_document_context import TabularFileContextPackage


def _lease_outline():
    return [
        OutlineSectionEntry("sr1", "ПРЕДМЕТ ДОГОВОРА", "1", 0, 200, "1. ПРЕДМЕТ ДОГОВОРА"),
        OutlineSectionEntry("sr5", "АРЕНДНАЯ ПЛАТА", "5", 500, 800, "5. АРЕНДНАЯ ПЛАТА"),
        OutlineSectionEntry("sr5_1", "Порядок оплаты", "5.1", 520, 700, "5.1 Порядок оплаты"),
        OutlineSectionEntry(
            "sr_app1",
            "Приложение №1",
            "1",
            2000,
            2100,
            "Приложение №1. Описание объекта",
        ),
        OutlineSectionEntry(
            "sr_app1_2",
            "Сведения об объекте",
            "2",
            2100,
            2500,
            "2. Сведения об объекте",
        ),
        OutlineSectionEntry(
            "sr_app2",
            "Приложение №2",
            "2",
            3000,
            3100,
            "Приложение №2. Акт",
        ),
        OutlineSectionEntry(
            "sr_app2_1",
            "Стороны",
            "1",
            3100,
            3400,
            "1. Стороны",
        ),
    ]


def test_parse_appendix_ref():
    refs = parse_contract_cross_references("согласно Приложению №1 к настоящему договору")
    assert refs
    assert refs[0].kind == "appendix"
    assert refs[0].appendix_no == "1"


def test_parse_clause_in_appendix():
    refs = parse_contract_cross_references("в соответствии с п. 2 Приложения №1")
    assert refs
    assert refs[0].kind == "appendix_clause"
    assert refs[0].appendix_no == "1"
    assert refs[0].clause_path == "2"


def test_parse_appendix_then_clause():
    refs = parse_contract_cross_references("см. Приложение №3 (п. 1.2)")
    assert any(r.kind == "appendix_clause" and r.appendix_no == "3" and r.clause_path == "1.2" for r in refs)


def test_parse_skips_federal_statute():
    text = "в соответствии со ст. 2 Федерального закона от 30.12.2009 N 384-ФЗ"
    refs = parse_contract_cross_references(text)
    assert not any(r.kind == "clause" and r.clause_path == "2" for r in refs)


def test_parse_section_ref_en():
    refs = parse_contract_cross_references("as set forth in Section 8.2 hereof")
    assert refs
    assert refs[0].anchor == "8.2"


def test_resolve_body_clause_not_appendix_collision():
    outline = _lease_outline()
    # Propagate via resolve helper (annotate happens inside).
    target = ContractRefTarget(kind="clause", anchor="1", raw="п. 1", clause_path="1")
    hits = resolve_ref_to_section_root_ids(target, outline)
    assert "sr1" in hits
    assert "sr_app2_1" not in hits


def test_resolve_appendix_root():
    outline = _lease_outline()
    target = ContractRefTarget(kind="appendix", anchor="1", raw="Приложение №1", appendix_no="1")
    hits = resolve_ref_to_section_root_ids(target, outline)
    assert hits == ("sr_app1",)


def test_resolve_appendix_clause():
    outline = _lease_outline()
    target = ContractRefTarget(
        kind="appendix_clause",
        anchor="1/2",
        raw="п. 2 Приложения №1",
        appendix_no="1",
        clause_path="2",
    )
    hits = resolve_ref_to_section_root_ids(target, outline)
    assert "sr_app1_2" in hits
    assert "sr5" not in hits


def test_resolve_section_prefix():
    outline = [
        ("sr8", "8", "TERMINATION", "8. TERMINATION"),
    ]
    target = ContractRefTarget(kind="clause", anchor="8.2", raw="Section 8.2", clause_path="8.2")
    hits = resolve_ref_to_section_root_ids(target, outline)
    assert hits == ("sr8",)


def test_outline_propagates_appendix_parts():
    chunks = [
        Document(
            page_content="body",
            metadata={
                "chunk_level": "macro",
                "section_root_id": "a",
                "section_title": "ПРЕДМЕТ",
                "section_number": "1",
                "char_start": 0,
                "char_end": 100,
            },
        ),
        Document(
            page_content="app",
            metadata={
                "chunk_level": "macro",
                "section_root_id": "b",
                "section_title": "Приложение №1",
                "section_number": "",
                "char_start": 200,
                "char_end": 250,
            },
        ),
        Document(
            page_content="part",
            metadata={
                "chunk_level": "macro",
                "section_root_id": "c",
                "section_title": "Описание",
                "section_number": "2",
                "char_start": 250,
                "char_end": 400,
            },
        ),
    ]
    outline, _ = build_outline_from_chunks(chunks)
    by_id = {e.section_root_id: e for e in outline}
    assert by_id["b"].section_kind == "appendix"
    assert by_id["b"].appendix_no == "1"
    assert by_id["c"].section_kind == "appendix_part"
    assert by_id["c"].appendix_no == "1"
    assert by_id["a"].section_kind == "body"


def test_collect_follow_prefers_appendix():
    outline = _lease_outline()
    ids, refs = collect_follow_section_ids(
        ["Стороны согласовали условия согласно Приложению №2 и п. 5.1"],
        outline,
        max_sections=3,
    )
    assert "sr_app2" in ids
    assert "sr5_1" in ids or "sr5" in ids
    assert any(r.kind == "appendix" for r in refs)


class _FakeVS:
    def __init__(self, macros):
        self.macros = macros

    def fetch_macro_chunks_by_section_root_ids(self, case_id, section_ids):
        out = {}
        for sid in section_ids:
            if sid in self.macros:
                out[sid] = self.macros[sid]
        return out


def test_enrich_pulls_appendix_macro(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_cross_ref_enrich.tabular_cross_ref_follow_enabled",
        lambda: True,
    )
    outline = tuple(
        # force propagation through resolve path; entries need kinds
        OutlineSectionEntry(*args)
        for args in [
            ("sr1", "ПРЕДМЕТ", "1", 0, 100, "1. ПРЕДМЕТ", "body", ""),
            ("sr_app1", "Приложение №1", "1", 200, 300, "Приложение №1", "appendix", "1"),
        ]
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
            page_content="Арендная плата указана в Приложении №1",
            metadata={"file_id": "f1", "cross_references": ["Приложение №1"]},
        )
    ]
    vs = _FakeVS(
        {
            "sr_app1": [
                Document(
                    page_content="Текст приложения один " * 20,
                    metadata={"file_id": "f1", "section_root_id": "sr_app1", "chunk_id": "m1"},
                )
            ]
        }
    )
    merged, meta = enrich_docs_with_cross_references(
        docs, file_context=pkg, vector_store=vs, case_id="c1", file_id="f1"
    )
    assert meta.get("cross_ref_enrich") is True
    assert "sr_app1" in meta.get("sections", [])
    assert len(merged) > len(docs)
