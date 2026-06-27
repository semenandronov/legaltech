"""Tests for structured table indexer."""

from app.services.legal_chunker import _Segment
from app.services.structured_table_indexer import StructuredTableIndexer

_TABLE_MD = """\
| Дата | Сумма | Описание |
|------|-------|----------|
| 27.06.2026 | -1 500.00 ₽ | Перевод |
| 25.06.2026 | -764.00 ₽ | Яндекс |
"""


def test_indexer_one_chunk_per_row():
    segments = [
        _Segment(
            text="Справка о движении средств\n\n",
            section_title="",
            section_number="",
            parent_path=[],
            page_no=1,
            char_start=0,
            char_end=30,
        ),
        _Segment(
            text=_TABLE_MD + "\n\n",
            section_title="",
            section_number="",
            parent_path=[],
            page_no=1,
            char_start=30,
            char_end=200,
            is_table=True,
        ),
    ]
    docs = StructuredTableIndexer().index(
        segments=segments,
        full_text="".join(s.text for s in segments),
        base_metadata={"doc_id": "d1", "file_id": "f1", "case_id": "c1"},
        preseg_strategy="docling_ast_native_text",
        filename="statement.pdf",
    )

    preamble = [d for d in docs if d.metadata.get("chunk_level") == "preamble"]
    rows = [d for d in docs if d.metadata.get("chunk_level") == "row"]

    assert len(preamble) == 1
    assert len(rows) == 2
    assert rows[0].metadata.get("global_row_index") == 0
    assert rows[1].metadata.get("global_row_index") == 1
    assert rows[0].metadata.get("chunking_contract_version") == "structured-table-v1"
    assert rows[0].metadata.get("index_profile") == "structured_table"
    assert "Яндекс" in rows[1].page_content
    assert rows[0].metadata.get("row_columns", {}).get("Сумма") == "-1 500.00 ₽"


def test_indexer_row_content_is_field_lines_not_pipe_blob():
    segments = [
        _Segment(
            text=_TABLE_MD + "\n\n",
            section_title="",
            section_number="",
            parent_path=[],
            page_no=2,
            char_start=0,
            char_end=100,
            is_table=True,
        ),
    ]
    docs = StructuredTableIndexer().index(
        segments=segments,
        full_text=segments[0].text,
        base_metadata={"doc_id": "d1"},
        preseg_strategy="test",
        filename="t.pdf",
    )
    row = next(d for d in docs if d.metadata.get("chunk_level") == "row")
    assert "|" not in row.page_content
    assert "Дата:" in row.page_content
    assert "Описание:" in row.page_content
