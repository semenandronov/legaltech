"""Tests for bank-statement table schema normalization."""

from app.services.table_schema_normalize import (
    cell_looks_like_amount,
    coalesce_header_union,
    lock_or_align_schema,
    lookup_column_value,
    looks_like_subtitle_row,
    normalize_stored_row_columns,
    parse_markdown_pipe_table_schema,
    primary_header_label,
    project_row_columns_to_headers,
    remap_row_columns_to_canonical,
)
from app.services.legal_chunker import _Segment
from app.services.structured_table_indexer import StructuredTableIndexer


def test_primary_header_from_br_and_footnote():
    assert primary_header_label("Дата операции<br>¹") == "Дата операции"
    assert (
        primary_header_label("Сумма в валюте карты<br>Сумма в валюте счета")
        == "Сумма в валюте карты"
    )
    assert primary_header_label("Описание операции¹") == "Описание операции"


def test_primary_header_splits_allcaps_glued_subtitle():
    assert primary_header_label("СУММА В ВАЛЮТЕ СЧЁТА Сумма В валюте") == (
        "Сумма В Валюте Счёта"
    )
    assert primary_header_label("ДАТА ОПЕРАЦИИ (МСК)") == "Дата Операции (МСК)"


def test_amount_detect_ignores_footnote_digit_in_word():
    assert not cell_looks_like_amount("Дата обработки1 и код авторизации")
    assert cell_looks_like_amount("279,00")
    assert cell_looks_like_amount("+8 000,00")
    assert cell_looks_like_amount("44,91")


def test_subtitle_row_with_footnote_digit_in_word():
    assert looks_like_subtitle_row(
        [
            "Дата обработки1 и код авторизации",
            "Дата обработки1 и код авторизации",
            "Описание операции",
            "операции?",
            "В валюте счёта",
        ]
    )


def test_parse_tbank_style_br_headers():
    md = "\n".join(
        [
            "| Дата операции<br>¹ | Сумма в валюте карты<br>² | "
            "Сумма в валюте счета<br>³ | Описание операции<br>⁴ |",
            "|---|---|---|---|",
            "| 10.01.2024 12:00 | -100,00 ₽ | -100,00 ₽ | Магнит |",
            "| 11.01.2024 13:00 | -50,00 ₽ | -50,00 ₽ | Такси |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert parsed.columns == [
        "Дата операции",
        "Сумма в валюте карты",
        "Сумма в валюте счета",
        "Описание операции",
    ]
    assert len(parsed.data_rows) == 2
    assert parsed.value_indices == [0, 1, 2, 3]


def test_parse_docling_tbank_page1_phantom_date_split():
    """Real Docling output: twin date columns + subtitle after separator + split rows."""
    md = "\n".join(
        [
            "| ДАТА ОПЕРАЦИИ (МСК) | ДАТА ОПЕРАЦИИ (МСК) | КАТЕГОРИЯ | "
            "СУММА В ВАЛЮТЕ СЧЁТА Сумма В валюте | ОСТАТОК СРЕДСТВ |",
            "|---|---|---|---|---|",
            "| Дата обработки1 и код авторизации | Дата обработки1 и код авторизации | "
            "Описание операции | операции? | В валюте счёта |",
            "| 10.07.2026 | 19.28 | Перевод c карты | | 44,91 |",
            '| 10.07.2026 | 887717 | АO "ТБанк" . Операция по карте ****6681 | | |',
            "| 10.07.2026 | 04.00 | Перевод на карту | +8 000,00 | 8 044,91 |",
            "| 10.07.2026 | 222847 | AUTOPLATEZH_PZP . Операция по карте | | |",
            "| 07.07.2026 | 17.01 | Прочие расходы | 279,00 | 44,91 |",
            "| 09.07.2026 | 166540 | ООО HEADHUNTER MOSKVA | | |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.columns) == 4
    assert parsed.columns[0] == "Дата Операции (МСК)"
    assert parsed.columns[1] == "Категория"
    assert "Сумма" in parsed.columns[2]
    assert parsed.columns[3] == "Остаток Средств"
    # Subtitle absorbed; continuation rows stitched → 3 logical operations.
    assert len(parsed.data_rows) == 3
    first = parsed.data_rows[0]
    assert "10.07.2026" in first[0]
    assert "19.28" in first[0]
    assert "887717" in first[0]
    assert "Перевод" in first[1]
    assert "ТБанк" in first[1]
    assert first[3] == "44,91"
    assert "date" in parsed.column_roles
    assert "amount" in parsed.column_roles
    assert "balance" in parsed.column_roles


def test_parse_two_row_headers_before_separator():
    md = "\n".join(
        [
            "| Дата операции | Сумма в валюте карты | Описание операции |",
            "| Дата и время | сумма списания | детали платежа |",
            "|---|---|---|",
            "| 10.01.2024 | -100,00 | Магнит |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert parsed.columns == [
        "Дата операции",
        "Сумма в валюте карты",
        "Описание операции",
    ]


def test_parse_drops_footnote_only_column_without_shifting():
    md = "\n".join(
        [
            "| Дата | ¹ | Сумма | Описание |",
            "|---|---|---|---|",
            "| 10.01.2024 | x | -100,00 | Магнит |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert parsed.columns == ["Дата", "Сумма", "Описание"]
    # After repair, rows are projected; indices become identity.
    assert parsed.value_indices == [0, 1, 2]
    assert parsed.data_rows[0] == ["10.01.2024", "-100,00", "Магнит"]


def test_coalesce_header_union_collapses_glued_variants():
    headers = [
        "Дата операции",
        "Дата операции ¹ Дата операции (МСК)",
        "Сумма в валюте карты",
        "Сумма в валюте карты Сумма списания",
        "1",
        "¹",
    ]
    out = coalesce_header_union(headers)
    assert out == ["Дата операции", "Сумма в валюте карты"]


def test_normalize_and_lookup_stored_row_columns():
    stored = {
        "Дата операции<br>¹": "10.01.2024",
        "Сумма в валюте карты Сумма списания": "-100",
    }
    normalized = normalize_stored_row_columns(stored)
    assert normalized["Дата операции"] == "10.01.2024"
    assert normalized["Сумма в валюте карты Сумма списания"] == "-100"
    assert lookup_column_value(stored, "Дата операции") == "10.01.2024"
    assert lookup_column_value(stored, "Сумма в валюте карты") == "-100"


def test_project_row_columns_to_headers():
    projected = project_row_columns_to_headers(
        {
            "Дата операции ¹ Дата операции (МСК)": "10.01.2024",
            "Сумма в валюте карты Сумма списания": "-100",
        },
        ["Дата операции", "Сумма в валюте карты"],
    )
    assert projected == {
        "Дата операции": "10.01.2024",
        "Сумма в валюте карты": "-100",
    }


def test_lock_schema_keeps_canonical_across_pages():
    page1 = ["Дата операции", "Сумма", "Описание"]
    page2 = ["Дата операции (МСК)", "Сумма операции", "Описание платежа"]
    schema, established = lock_or_align_schema(local_columns=page1, canonical=None)
    assert established is True
    schema2, established2 = lock_or_align_schema(local_columns=page2, canonical=schema)
    assert established2 is False
    assert schema2 == page1


def test_remap_row_columns_positional_when_arity_matches():
    local = {
        "Дата операции (МСК)": "10.01.2024",
        "Сумма операции": "-100",
        "Описание платежа": "Магнит",
    }
    canonical = ["Дата операции", "Сумма", "Описание"]
    remapped = remap_row_columns_to_canonical(local, canonical)
    assert remapped == {
        "Дата операции": "10.01.2024",
        "Сумма": "-100",
        "Описание": "Магнит",
    }


def test_indexer_locks_canonical_across_two_table_segments(monkeypatch):
    monkeypatch.setattr(
        "app.services.structured_table_indexer._min_transaction_rows",
        lambda: 2,
    )

    page1 = "\n".join(
        [
            "| Дата операции<br>¹ | Сумма<br>² | Описание<br>³ |",
            "|---|---|---|",
            "| 10.01.2024 | -100,00 | A |",
            "| 11.01.2024 | -50,00 | B |",
        ]
    )
    page2 = "\n".join(
        [
            "| Дата операции (МСК) | Сумма операции | Описание платежа |",
            "|---|---|---|",
            "| 12.01.2024 | -30,00 | C |",
            "| 13.01.2024 | -20,00 | D |",
        ]
    )
    segments = [
        _Segment(
            text=page1 + "\n\n",
            section_title="",
            section_number="",
            parent_path=[],
            page_no=1,
            char_start=0,
            char_end=100,
            is_table=True,
        ),
        _Segment(
            text=page2 + "\n\n",
            section_title="",
            section_number="",
            parent_path=[],
            page_no=2,
            char_start=100,
            char_end=200,
            is_table=True,
        ),
    ]
    docs = StructuredTableIndexer().index(
        segments=segments,
        full_text="".join(s.text for s in segments),
        base_metadata={"doc_id": "d1", "case_id": "c1"},
        preseg_strategy="test",
        filename="tbank.pdf",
    )
    rows = [d for d in docs if d.metadata.get("chunk_level") == "row"]
    assert len(rows) == 4
    keys = set(rows[0].metadata["row_columns"].keys())
    assert keys == {"Дата операции", "Сумма", "Описание"}
    assert set(rows[2].metadata["row_columns"].keys()) == keys
    assert rows[2].metadata["row_columns"]["Описание"] == "C"


def test_indexer_repairs_docling_phantom_columns(monkeypatch):
    monkeypatch.setattr(
        "app.services.structured_table_indexer._min_transaction_rows",
        lambda: 2,
    )
    md = "\n".join(
        [
            "| ДАТА ОПЕРАЦИИ (МСК) | ДАТА ОПЕРАЦИИ (МСК) | КАТЕГОРИЯ | "
            "СУММА В ВАЛЮТЕ СЧЁТА Сумма В валюте | ОСТАТОК СРЕДСТВ |",
            "|---|---|---|---|---|",
            "| Дата обработки1 и код авторизации | Дата обработки1 и код авторизации | "
            "Описание операции | операции? | В валюте счёта |",
            "| 10.07.2026 | 19.28 | Перевод c карты | 100,00 | 44,91 |",
            "| 10.07.2026 | 887717 | Merchant details here | | |",
            "| 09.07.2026 | 11.28 | Такси | 50,00 | 323,91 |",
            "| 09.07.2026 | 023880 | YANDEX GO MOSCOW | | |",
        ]
    )
    docs = StructuredTableIndexer().index(
        segments=[
            _Segment(
                text=md + "\n\n",
                section_title="",
                section_number="",
                parent_path=[],
                page_no=1,
                char_start=0,
                char_end=200,
                is_table=True,
            )
        ],
        full_text=md,
        base_metadata={"doc_id": "d1", "case_id": "c1"},
        preseg_strategy="test",
        filename="stmt.pdf",
    )
    rows = [d for d in docs if d.metadata.get("chunk_level") == "row"]
    assert len(rows) == 2
    cols = list(rows[0].metadata["row_columns"].keys())
    assert len(cols) == 4
    assert "Дата Операции (МСК)" in cols
    assert rows[0].metadata.get("column_roles")
