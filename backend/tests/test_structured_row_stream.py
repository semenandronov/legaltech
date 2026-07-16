"""Canonical structured-row text stream ↔ char span contract."""

from langchain_core.documents import Document

from app.services.structured_file_text import (
    STRUCTURED_ROW_SEPARATOR,
    align_structured_table_row_stream,
    join_structured_row_bodies,
    structured_row_char_spans,
)


def test_structured_row_spans_match_joined_text():
    bodies = [
        "Дата: 01.01.2024\nСумма: 10,00",
        "Дата: 02.01.2024\nСумма: 20,00",
        "Дата: 03.01.2024\nСумма: 30,00",
    ]
    joined = join_structured_row_bodies(bodies)
    spans = structured_row_char_spans(bodies)
    assert STRUCTURED_ROW_SEPARATOR.join(bodies) == joined
    assert len(spans) == 3
    for body, start, end in spans:
        assert joined[start:end] == body
    # Drift that the old body+"\\n" indexer produced must not appear.
    assert spans[1][0] == bodies[1]
    assert spans[1][1] == len(bodies[0]) + len(STRUCTURED_ROW_SEPARATOR)


def test_align_structured_table_row_stream_rewrites_offsets():
    docs = [
        Document(
            page_content="Дата операции: 01.01.2024\nСумма: 10,00\n",
            metadata={
                "chunk_level": "row",
                "index_profile": "structured_table",
                "preseg_strategy": "statement_geometry_native",
                "char_start": 0,
                "char_end": 99,  # intentionally wrong
                "global_row_index": 0,
            },
        ),
        Document(
            page_content="Дата операции: 02.01.2024\nСумма: 20,00",
            metadata={
                "chunk_level": "row",
                "index_profile": "structured_table",
                "preseg_strategy": "statement_geometry_native",
                "char_start": 100,
                "char_end": 200,
                "global_row_index": 1,
            },
        ),
    ]
    aligned, joined = align_structured_table_row_stream(docs)
    assert joined is not None
    assert len(aligned) == 2
    for doc in aligned:
        cs = int(doc.metadata["char_start"])
        ce = int(doc.metadata["char_end"])
        assert joined[cs:ce] == doc.page_content
        assert doc.metadata.get("char_basis") == "structured_row_stream"
        assert not doc.page_content.endswith("\n")
