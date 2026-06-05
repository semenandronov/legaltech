"""Citation file identity: source_id must be case File.id, not doc_N labels."""

from langchain_core.documents import Document

from app.services.chat.citation_file_identity import (
    CaseCitationFileIndex,
    is_synthetic_doc_label,
    parse_passport_filename,
    resolve_citation_file_identity,
)
from app.services.chat.citation_payload import build_retrieval_citations


def test_is_synthetic_doc_label():
    assert is_synthetic_doc_label("doc_1")
    assert is_synthetic_doc_label("doc_0")
    assert is_synthetic_doc_label("unknown")
    assert not is_synthetic_doc_label("a3f2b8c1-4e5f-4a2b-9c8d-1e2f3a4b5c6d")


def test_parse_passport_filename():
    text = "Файл: 03. договор от 16.04.2024 на 14л.pdf\nТип: договор\nКраткое содержание: …"
    assert parse_passport_filename(text) == "03. договор от 16.04.2024 на 14л.pdf"


def test_resolve_passport_overview_via_catalog():
    fid_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    fid_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    index = CaseCitationFileIndex.from_file_map(
        {
            fid_a: "03. договор от 16.04.2024 на 14л.pdf",
            fid_b: "04. договор от 16.04.2024 на 5л.pdf",
        },
        ordered_file_ids=[fid_a, fid_b],
    )
    passage = (
        "Файл: 03. договор от 16.04.2024 на 14л.pdf\n"
        "Тип: договор\n"
        "Краткое содержание: Договор подряда."
    )
    meta = {
        "file_id": fid_a,
        "filename": "03. договор от 16.04.2024 на 14л.pdf",
        "chunk_level": "passport",
    }
    resolved_id, name = resolve_citation_file_identity(meta, passage, retrieval_d=1, index=index)
    assert resolved_id == fid_a
    assert "договор" in name


def test_build_citations_rejects_doc_n_labels_uses_catalog():
    """Regression: metadata doc_1 + passport text → real file UUID in source_id."""
    fid_a = "11111111-1111-1111-1111-111111111111"
    fid_b = "22222222-2222-2222-2222-222222222222"
    index = CaseCitationFileIndex.from_file_map(
        {
            fid_a: "03. договор от 16.04.2024 на 14л.pdf",
            fid_b: "04. договор от 16.04.2024 на 5л.pdf",
        },
        ordered_file_ids=[fid_a, fid_b],
    )
    docs = [
        Document(
            page_content=(
                "Файл: 03. договор от 16.04.2024 на 14л.pdf\n"
                "Тип: договор\n"
                "Краткое содержание: Договор подряда №98/2024."
            ),
            metadata={
                "doc_id": "doc_0",
                "source_file": "doc_1",
                "filename": "doc_1",
                "chunk_id": "doc_0_0_fb9ab9",
                "char_start": 0,
                "char_end": 100,
            },
        ),
        Document(
            page_content=(
                "Файл: 04. договор от 16.04.2024 на 5л.pdf\n"
                "Тип: договор\n"
                "Краткое содержание: Договор поставки №54."
            ),
            metadata={
                "doc_id": "doc_1",
                "source_file": "doc_2",
                "filename": "doc_2",
                "chunk_id": "doc_1_1_0ced4a",
                "char_start": 0,
                "char_end": 80,
            },
        ),
    ]
    cites = build_retrieval_citations(docs, case_file_index=index)
    assert len(cites) == 2
    assert cites[0]["source_id"] == fid_a
    assert cites[0]["file_name"] == "03. договор от 16.04.2024 на 14л.pdf"
    assert cites[1]["source_id"] == fid_b
    assert not is_synthetic_doc_label(cites[0]["source_id"])
    assert "договор" in (cites[0]["file_name"] or "")
