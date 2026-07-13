"""Tabular citation policy: row-only evidence for Excel/registers."""
from __future__ import annotations

from langchain_core.documents import Document

from app.services.chat.scoped_file_expand import _inventory_from_chunks_and_text
from app.services.chat.tabular_citation_policy import (
    filter_docs_for_tabular_citations,
    inventory_is_structured_table_rows,
    looks_like_multi_row_register_dump,
    should_exclude_tabular_dump_document,
)


def _row(fid: str, n: int, desc: str) -> Document:
    return Document(
        page_content=f"№: {n}\nДата: 06.04.2026\nОписание операции: {desc}\nСумма: -99.00 ₽",
        metadata={
            "file_id": fid,
            "source_file": "ops.xlsx",
            "chunk_level": "row",
            "index_profile": "structured_table",
            "row_columns": {
                "№": str(n),
                "Дата": "06.04.2026",
                "Описание операции": desc,
                "Сумма": "-99.00 ₽",
            },
        },
    )


def test_looks_like_multi_row_register_dump():
    dump = (
        "Операции\n№\nДата\nНомер карты\nДата списания\nОписание операции\n"
        "Сумма в валюте операции\n"
        "1\n06.04.2026 22:54\n06.04.2026 22:54\nПлата\n-99\n"
        "2\n06.04.2026 22:32\n06.04.2026 22:32\nКэшбэк\n+331\n"
        "3\n06.05.2026 22:52\n06.05.2026 22:52\nПлата\n-99\n"
    )
    assert looks_like_multi_row_register_dump(dump) is True
    row = "№: 1\nДата: 06.04.2026\nОписание операции: Плата\nСумма: -99.00 ₽"
    assert looks_like_multi_row_register_dump(row) is False


def test_inventory_is_structured_table_rows():
    rows = [_row("f1", i, "Плата") for i in range(1, 6)]
    assert inventory_is_structured_table_rows(rows) is True
    assert inventory_is_structured_table_rows(rows[:1]) is False


def test_filter_docs_drops_original_windows_when_rows_present():
    rows = [_row("f1", i, f"Op {i}") for i in range(1, 5)]
    dump = Document(
        page_content=(
            "Операции\n№\nДата\nНомер карты\nДата списания\nОписание операции\n"
            "Сумма в валюте операции\n"
            "1\n06.04.2026 22:54\n06.04.2026 22:54\nПлата\n-99\n"
            "2\n06.05.2026 22:52\n06.05.2026 22:52\nПлата\n-99\n"
            "3\n06.06.2026 22:48\n06.06.2026 22:48\nПлата\n-99\n"
        ),
        metadata={
            "file_id": "f1",
            "within_file_source": "original_window",
            "window_index": 0,
        },
    )
    filtered = filter_docs_for_tabular_citations([*rows, dump])
    assert len(filtered) == 4
    assert all(is_row(d) for d in filtered)
    assert should_exclude_tabular_dump_document(
        dump, structured_file_ids={"f1"}
    )


def is_row(doc: Document) -> bool:
    return (doc.metadata or {}).get("chunk_level") == "row"


def test_structured_inventory_skips_original_text_windows():
    rows = [_row("f1", i, f"Op {i}") for i in range(1, 5)]
    sheet = (
        "Операции\n№\nДата\nНомер карты\nДата списания\nОписание операции\n"
        + "\n".join(f"{i}\n06.0{i}.2026\nплата\n-99" for i in range(1, 6))
    )
    inventory, edges = _inventory_from_chunks_and_text(
        chunks=rows,
        file_id="f1",
        original_text=sheet,
    )
    assert edges == []
    assert all((d.metadata or {}).get("within_file_source") == "vector" for d in inventory)
    assert len(inventory) == 4
