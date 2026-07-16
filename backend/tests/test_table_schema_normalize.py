"""Tests for bank-statement table schema normalization."""

from app.services.table_schema_normalize import (
    cell_looks_like_amount,
    coalesce_header_union,
    lock_or_align_schema,
    lookup_column_value,
    looks_like_subtitle_row,
    normalize_date_cell,
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


def test_normalize_date_cell_dedupes_triple_date():
    assert normalize_date_cell("11.02.2025 11.02.2025 11.02.2025") == "11.02.2025"
    assert normalize_date_cell("10.07.2026 19.28 887717") == "10.07.2026 19.28 887717"


def test_parse_sber_debit_page_break_stitch_and_date_dedup():
    """Debit-card statement: page break splits 'Операция по' / 'карте' + balance footer."""
    md = "\n".join(
        [
            "| № | Дата | Категория | Остаток | Дата Операции МСК |",
            "|---|---|---|---|---|",
            "| 940 | 11.02.2025 11.02.2025 11.02.2025 | "
            "Покупка. Операция по | | 11.02.2025 |",
            "| | | карте | 1 743,19 | |",
            "| 941 | 12.02.2025 | Перевод | 1 243,19 | 12.02.2025 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    row940 = parsed.data_rows[0]
    assert row940[1] == "11.02.2025"
    assert "Операция по карте" in row940[2]
    assert row940[3] == "1 743,19"
    assert "940" in row940[0]
    row941 = parsed.data_rows[1]
    assert "Перевод" in row941[2]
    assert row941[3] == "1 243,19"


def test_stitch_open_desc_when_amount_lands_on_tail():
    """Real pattern: '...Операция по' without amount + 'карте ****' with amount."""
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 26.12.2025 | Перевод с карты Перевод для А. Семён Андреевич. Операция по | | |",
            "| 26.12.2025 | карте ****6681 | 5 300,25 | 0,00 |",
            "| 26.12.2025 | Перевод на карту | +8 000,00 | 8 000,25 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    first = parsed.data_rows[0]
    assert "Операция по карте ****6681" in first[1]
    assert first[2] == "5 300,25"
    assert first[3] == "0,00"


def test_unglue_packed_next_op_then_stitch_tail():
    """Description packs next op head; next row is orphan 'карте' with amount."""
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 11.02.2025 | Рестораны и кафе EVRAZIYA SANKT-PETERBU RUS. "
            "Операция по карте ****6681 Перевод на карту Перевод от A. | 1 200,50 | 542,69 |",
            "| 11.02.2025 | карте | +1 482,85 | 1 743,19 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    first, second = parsed.data_rows
    assert first[1].endswith("Операция по карте ****6681")
    assert "Перевод" not in first[1]
    assert first[2] == "1 200,50"
    assert "Перевод на карту" in second[1]
    assert "Операция по карте" in second[1]
    assert second[2] == "+1 482,85"


def test_explode_dual_operation_in_one_cell():
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 03.07.2024 | Супермаркеты PEKARNYA BUKHANKA Gorod Sankt-P RUS. "
            "Операция по карте ****6681 Перевод с карты Перевод для Ф. Анастасия "
            "Дмитриевна. Операция по карте ****6681 | 85,00 | 5 531,58 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    first, second = parsed.data_rows
    assert first[1].endswith("Операция по карте ****6681")
    assert "Перевод" not in first[1]
    assert first[2] == "85,00"
    assert "Перевод с карты" in second[1]
    assert second[2] == ""


def test_realign_time_in_category_description_in_amount():
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 06.07.2024 | 21:07 535423 | "
            "Супермаркеты LENTA-738 Pargolovo RUS. Операция по карте ****6681 | 679,85 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 1
    row = parsed.data_rows[0]
    assert "21:07" in row[0] and "535423" in row[0]
    assert "LENTA-738" in row[1]
    assert row[2] == ""
    assert row[3] == "679,85"


def test_locked_schema_drops_repeated_header_on_page2():
    page1 = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 10.07.2026 | Перевод на карту | +8 000,00 | 8 044,91 |",
        ]
    )
    first = parse_markdown_pipe_table_schema(page1)
    assert first is not None
    page2 = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| Дата обработки и код | Описание операции | Сумма | Остаток |",
            "| 09.07.2026 | Супермаркеты LENTA | 100,00 | 200,00 |",
        ]
    )
    second = parse_markdown_pipe_table_schema(
        page2,
        locked_columns=first.columns,
        locked_roles=list(first.column_roles),
    )
    assert second is not None
    assert second.columns == first.columns
    assert len(second.data_rows) == 1
    assert "LENTA" in second.data_rows[0][1]
    assert "schema_locked" in second.quality_warnings


def test_stitch_mask_only_tail_after_open_card_text():
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 05.07.2024 | Транспорт bilet.nspk.ru. Операция по карте | | |",
            "| 06.07.2024 | ****6681 | 65,00 | 5 939,66 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 1
    row = parsed.data_rows[0]
    assert "****6681" in row[1]
    assert row[2] == "65,00"


def test_stitch_category_head_and_merchant_spill():
    """Category label and merchant body split across Docling rows."""
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 12.07.2026 | Супермаркеты | | |",
            "| 12.07.2026 | MAGAZIN KEDR >MOSKVA RUS. Операция по карте ****0805 | 1 245,90 | 3 100,00 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 1
    row = parsed.data_rows[0]
    assert row[1].startswith("Супермаркеты MAGAZIN KEDR")
    assert "Операция по карте ****0805" in row[1]
    assert row[2] == "1 245,90"


def test_unglue_account_op_then_category_merchant_chain():
    """Packed '...по счёту **** N Супермаркеты' + merchant row → two clean ops."""
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 11.07.2026 | Перевод СБП AUTOPLATEZH. Операция по счету ****0805 "
            "Супермаркеты | 500,00 | 4 000,00 |",
            "| 11.07.2026 | MAGAZIN KEDR >MOSKVA RUS. Операция по карте ****0805 | "
            "1 245,90 | 2 754,10 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    first, second = parsed.data_rows
    assert first[1].endswith("Операция по счету ****0805")
    assert "Супермаркеты" not in first[1]
    assert first[2] == "500,00"
    assert second[1].startswith("Супермаркеты MAGAZIN KEDR")
    assert second[2] == "1 245,90"


def test_stitch_qr_channel_head_with_merchant_continuation():
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 10.07.2026 | Оплата по QR-коду СБП | | |",
            "| 10.07.2026 | RE. Операция по карте ****0805 | 350,00 | 9 650,00 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 1
    row = parsed.data_rows[0]
    assert "Оплата по QR-коду СБП" in row[1]
    assert "RE." in row[1]
    assert row[2] == "350,00"


def test_drop_orphan_bare_category_without_amount():
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 09.07.2026 | Перевод на карту | +1 000,00 | 5 000,00 |",
            "| 09.07.2026 | Супермаркеты | | |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 1
    assert "Перевод на карту" in parsed.data_rows[0][1]


def test_assess_operation_row_quality_flags_missing_amount():
    from app.services.table_schema_normalize import assess_operation_row_quality

    score, warnings = assess_operation_row_quality(
        {
            "Дата Операции (МСК)": "10.07.2026",
            "Категория": "Супермаркеты LENTA",
            "Сумма В Валюте Счёта": "",
            "Остаток Средств": "100,00",
        },
        column_roles=["date", "category", "amount", "balance"],
    )
    assert score < 1.0
    assert "missing_amount" in warnings


def test_stitch_amount_on_thin_qr_head_body_on_next_row():
    """Amount on thin QR head + merchant body (Latin) without amount → one op."""
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 20.06.2026 | Оплата по QR-коду СБП | 1 720,00 | 5 694,16 |",
            "| 20.06.2026 | RE. Операция по карте ****7035 | | |",
            "| 20.06.2026 | Оплата по QR-коду СБП ООО БУРГЕР РУС. "
            "Операция по карте ****7035 | 279,99 | 7 414,16 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    first, second = parsed.data_rows
    assert first[1].startswith("Оплата по QR-коду СБП RE.")
    assert "****7035" in first[1]
    assert first[2] == "1 720,00"
    assert "БУРГЕР" in second[1]
    assert second[2] == "279,99"


def test_stitch_amount_on_thin_qr_head_cyrillic_merchant_body():
    """Amount on thin QR head + Cyrillic merchant body (Сервисы Яндекса) → one op."""
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 20.06.2026 | Оплата по QR-коду СБП | 1 720,00 | 5 694,16 |",
            "| 20.06.2026 | Сервисы Яндекса. Операция по карте ****7035 | | |",
            "| 20.06.2026 | Оплата по QR-коду СБП ООО БУРГЕР РУС. "
            "Операция по карте ****7035 | 279,99 | 7 414,16 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    first, second = parsed.data_rows
    assert first[1].startswith("Оплата по QR-коду СБП Сервисы Яндекса")
    assert "****7035" in first[1]
    assert first[2] == "1 720,00"
    assert "БУРГЕР" in second[1]
    assert second[2] == "279,99"


def test_do_not_stitch_qr_head_onto_standalone_channel_op():
    """QR thin head must not absorb a sibling channel-headed op (Супермаркеты…)."""
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 07.06.2026 | Оплата по QR-коду СБП | 200,00 | 7 117,47 |",
            "| 07.06.2026 | Супермаркеты MAGAZIN NORDIK MIRNYJ RUS. "
            "Операция по карте ****7035 | | |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    assert parsed.data_rows[0][1] == "Оплата по QR-коду СБП"
    assert "NORDIK" in parsed.data_rows[1][1]
    assert parsed.data_rows[1][2] == ""


def test_do_not_stitch_complete_funded_op_onto_next_missing_amount():
    """Independent op without amount stays separate when previous is already complete."""
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 07.06.2026 | Оплата по QR-коду СБП case-battle. "
            "Операция по карте ****7035 | 200,00 | 7 117,47 |",
            "| 07.06.2026 | Супермаркеты MAGAZIN NORDIK MIRNYJ RUS. "
            "Операция по карте ****7035 | | |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    assert "case-battle" in parsed.data_rows[0][1]
    assert "NORDIK" in parsed.data_rows[1][1]
    assert parsed.data_rows[1][2] == ""


def test_normalize_date_cell_keeps_first_of_dual_calendar_dates():
    assert normalize_date_cell("08.06.2026 09.06.2026") == "08.06.2026"
    assert normalize_date_cell("04.06.2026 05.06.2026 17:01") == "04.06.2026 17:01"


def test_stitch_transfer_head_with_attribution_body():
    """Thin «Перевод на карту» + amount, then «Перевод от … Операция по карте» → one op."""
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 09.07.2026 00:28 | Перевод на карту | +5 051,28 | 7 507,91 |",
            "| 09.07.2026 622521 | Перевод от А. Семён Андреевич. "
            "Операция по карте ****6681 | | 11 031,43 |",
            "| 09.07.2026 00:18 | Оплата по QR-коду СБП SBSCR. "
            "Операция по карте ****6681 | 349,00 | 2 456,63 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    first = parsed.data_rows[0]
    assert first[2] == "+5 051,28"
    assert first[3] == "7 507,91"
    assert "Перевод на карту" in first[1]
    assert "Семён" in first[1] or "Семен" in first[1]
    assert "****6681" in first[1]
    assert "622521" in first[0]


def test_drop_table_header_echo_row():
    """Mid-page column-title echo is not a transaction."""
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 20.10.2025 12:00 | Супермаркеты MAGNIT. Операция по карте ****1 | 100,00 | 500,00 |",
            "| и код авторизации | Описание операции | Сумма в валюте операции 2 | 8 202,60 |",
            "| 21.10.2025 13:00 | Оплата по QR-коду СБП cafe. Операция по карте ****1 | 50,00 | 450,00 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    assert "MAGNIT" in parsed.data_rows[0][1]
    assert "cafe" in parsed.data_rows[1][1]


def test_stitch_body_then_amount_on_thin_head():
    """Merchant body first (no money), thin category head with money next → one op."""
    md = "\n".join(
        [
            "| Дата Операции (МСК) | Категория | Сумма В Валюте Счёта | Остаток Средств |",
            "|---|---|---|---|",
            "| 08.01.2026 | Прочие расходы REG.RU SAMARA RUS. Операция по карте ****6681 | | |",
            "| 09.01.2026 | Прочие расходы | 494,00 | 0,00 |",
            "| 10.01.2026 | Оплата по QR-коду СБП x. Операция по карте ****1 | 10,00 | 100,00 |",
        ]
    )
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    first = parsed.data_rows[0]
    assert first[2] == "494,00"
    assert first[3] == "0,00"
    assert "REG.RU" in first[1]
    assert "Прочие расходы" in first[1]
