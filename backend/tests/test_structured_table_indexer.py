"""Tests for structured table indexer (hybrid narrative + row chunks)."""

import pytest

from app.services.legal_chunker import _Segment
from app.services.structured_table_indexer import (
    StructuredTableIndexer,
    is_transaction_table_segment,
)


def _table_md(rows: int) -> str:
  lines = [
      "| Дата | Сумма | Описание |",
      "|------|-------|----------|",
  ]
  for i in range(rows):
      lines.append(f"| 27.06.2026 | -{100 + i}.00 ₽ | Операция {i} |")
  return "\n".join(lines) + "\n"


_TABLE_MD = _table_md(2)


@pytest.fixture
def min_rows_2(monkeypatch):
    monkeypatch.setattr(
        "app.services.structured_table_indexer._min_transaction_rows",
        lambda: 2,
    )


def test_is_transaction_table_segment_respects_row_threshold():
    small = _Segment(
        text=_TABLE_MD,
        section_title="",
        section_number="",
        parent_path=[],
        page_no=1,
        char_start=0,
        char_end=100,
        is_table=True,
    )
    large = _Segment(
        text=_table_md(10),
        section_title="",
        section_number="",
        parent_path=[],
        page_no=2,
        char_start=0,
        char_end=100,
        is_table=True,
    )
    assert not is_transaction_table_segment(small)
    assert is_transaction_table_segment(large)


def test_indexer_hybrid_narrative_header_and_row_table(min_rows_2):
    segments = [
        _Segment(
            text="Справка о движении средств\n\nТ-Банк\n\n",
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

    narrative = [
        d
        for d in docs
        if d.metadata.get("chunk_level") in ("macro", "micro")
    ]
    rows = [d for d in docs if d.metadata.get("chunk_level") == "row"]
    preambles = [d for d in docs if d.metadata.get("chunk_level") == "preamble"]

    assert len(narrative) >= 1
    assert len(rows) == 2
    assert len(preambles) == 0
    assert any("Справка" in (d.page_content or "") for d in narrative)
    assert rows[0].metadata.get("global_row_index") == 0
    assert rows[1].metadata.get("global_row_index") == 1
    assert rows[0].metadata.get("chunking_contract_version") == "structured-table-v1"
    assert rows[0].metadata.get("index_profile") == "structured_table"
    assert narrative[0].metadata.get("hybrid_file_profile") == "structured_table"
    assert "Операция 1" in rows[1].page_content
    assert rows[0].metadata.get("row_columns", {}).get("Сумма") == "-100.00 ₽"


def test_indexer_row_content_is_field_lines_not_pipe_blob(min_rows_2):
    segments = [
        _Segment(
            text=_table_md(3) + "\n\n",
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
        base_metadata={"doc_id": "d1", "case_id": "c1"},
        preseg_strategy="test",
        filename="t.pdf",
    )
    row = next(d for d in docs if d.metadata.get("chunk_level") == "row")
    assert "|" not in row.page_content
    assert "Дата:" in row.page_content
    assert "Описание:" in row.page_content


def test_small_table_stays_in_narrative_not_rows():
    """Header-style tables with few rows must not become operation row chunks."""
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
        base_metadata={"doc_id": "d1", "case_id": "c1"},
        preseg_strategy="test",
        filename="statement.pdf",
    )
    assert not any(d.metadata.get("chunk_level") == "row" for d in docs)
    assert any(d.metadata.get("chunk_level") in ("macro", "micro") for d in docs)
