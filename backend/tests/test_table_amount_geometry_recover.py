"""Tests for PDF geometry recovery of operation table cells."""

from app.services.docling_table_geometry import PdfWord
from app.services.table_amount_geometry_recover import (
    recover_missing_amount_cells,
    recover_operation_table_from_page_geometry,
)
from app.services.table_schema_normalize import ColumnRole


COLUMNS = [
    "Дата Операции (МСК)",
    "Категория",
    "Сумма В Валюте Счёта",
    "Остаток Средств",
]
ROLES = [
    ColumnRole.DATE,
    ColumnRole.CATEGORY,
    ColumnRole.AMOUNT,
    ColumnRole.BALANCE,
]


def test_recover_missing_amount_from_page_words():
    matrix = [
        ["20.06.2026", "Оплата QR FUNPAY", "352,60", "5 341,56"],
        ["20.06.2026", "Сервисы Яндекса. Операция по карте ****7035", "", ""],
        ["20.06.2026", "Оплата QR BURGER", "279,99", "7 414,16"],
    ]
    words = [
        PdfWord(x=80, y_bottom=700, y_top=100, text="20.06.2026"),
        PdfWord(x=200, y_bottom=700, y_top=100, text="FUNPAY"),
        PdfWord(x=400, y_bottom=700, y_top=100, text="352,60"),
        PdfWord(x=520, y_bottom=700, y_top=100, text="5"),
        PdfWord(x=535, y_bottom=700, y_top=100, text="341,56"),
        PdfWord(x=80, y_bottom=680, y_top=120, text="20.06.2026"),
        PdfWord(x=200, y_bottom=680, y_top=120, text="Яндекса"),
        PdfWord(x=400, y_bottom=680, y_top=120, text="39,01"),
        PdfWord(x=80, y_bottom=660, y_top=140, text="20.06.2026"),
        PdfWord(x=200, y_bottom=660, y_top=140, text="BURGER"),
        PdfWord(x=400, y_bottom=660, y_top=140, text="279,99"),
        PdfWord(x=520, y_bottom=660, y_top=140, text="7"),
        PdfWord(x=535, y_bottom=660, y_top=140, text="414,16"),
    ]
    out, n = recover_missing_amount_cells(COLUMNS, matrix, ROLES, words)
    assert n >= 1
    assert out[1][2] == "39,01"
    assert out[0][2] == "352,60"
    assert out[2][2] == "279,99"


def test_recover_amount_and_balance_on_line_above_merchant():
    """Amount + balance on spine line above merchant body."""
    matrix = [
        ["25.06.2026", "Оплата QR RE. Операция по карте ****7035", "1 411,00", "3 875,77"],
        ["25.06.2026", "Сервисы Яндекса. Операция по карте ****7035", "", ""],
    ]
    words = [
        # Complete sibling op (higher on page = smaller y_top)
        PdfWord(x=80, y_bottom=420, y_top=420, text="25.06.2026"),
        PdfWord(x=200, y_bottom=420, y_top=420, text="RE"),
        PdfWord(x=430, y_bottom=420, y_top=420, text="1 411,00"),
        PdfWord(x=520, y_bottom=420, y_top=420, text="3 875,77"),
        # Amount spine for Yandex (below RE)
        PdfWord(x=80, y_bottom=400, y_top=440, text="25.06.2026"),
        PdfWord(x=200, y_bottom=400, y_top=440, text="Оплата"),
        PdfWord(x=240, y_bottom=400, y_top=440, text="по"),
        PdfWord(x=260, y_bottom=400, y_top=440, text="QR-коду"),
        PdfWord(x=320, y_bottom=400, y_top=440, text="СБП"),
        PdfWord(x=430, y_bottom=400, y_top=440, text="2 379,00"),
        PdfWord(x=520, y_bottom=400, y_top=440, text="1 496,77"),
        # Merchant body below amount spine
        PdfWord(x=80, y_bottom=390, y_top=451, text="25.06.2026"),
        PdfWord(x=200, y_bottom=390, y_top=451, text="Яндекса"),
    ]
    out, stats = recover_operation_table_from_page_geometry(
        COLUMNS, matrix, ROLES, words
    )
    assert stats.amounts == 1
    assert stats.balances == 1
    assert out[1][2] == "2 379,00"
    assert out[1][3] == "1 496,77"
    assert "Оплата" in out[1][1] or "QR" in out[1][1]
    assert "Яндекса" in out[1][1]


def test_recover_does_not_invent_when_no_money_in_band():
    matrix = [
        ["01.01.2026", "Оплата A", "100,00", "200,00"],
        ["02.01.2026", "Оплата B missing", "", ""],
    ]
    words = [
        PdfWord(x=50, y_bottom=500, y_top=50, text="01.01.2026"),
        PdfWord(x=300, y_bottom=500, y_top=50, text="100,00"),
        PdfWord(x=50, y_bottom=480, y_top=70, text="02.01.2026"),
        PdfWord(x=50, y_bottom=480, y_top=70, text="only"),
    ]
    out, n = recover_missing_amount_cells(COLUMNS, matrix, ROLES, words)
    assert n == 0
    assert out[1][2] == ""


def test_insert_missing_amount_balance_spine_row():
    """Amount+balance pair present on page but absent from Docling matrix → insert."""
    matrix = [
        ["19.06.2026", "Оплата Додо. Операция по карте ****1", "2 721,00", "7 694,15"],
        ["18.06.2026", "Супермаркеты NORDIK. Операция по карте ****1", "460,00", "3 415,15"],
    ]
    words = [
        PdfWord(x=45, y_bottom=740, y_top=96, text="19.06.2026"),
        PdfWord(x=102, y_bottom=740, y_top=96, text="10:44"),
        PdfWord(x=152, y_bottom=740, y_top=96, text="Оплата"),
        PdfWord(x=200, y_bottom=740, y_top=96, text="Додо"),
        PdfWord(x=430, y_bottom=740, y_top=96, text="2 721,00"),
        PdfWord(x=525, y_bottom=740, y_top=96, text="7 694,15"),
        PdfWord(x=152, y_bottom=728, y_top=108, text="Пицца."),
        PdfWord(x=200, y_bottom=728, y_top=108, text="Операция"),
        PdfWord(x=260, y_bottom=728, y_top=108, text="по"),
        PdfWord(x=280, y_bottom=728, y_top=108, text="карте"),
        PdfWord(x=320, y_bottom=728, y_top=108, text="****1"),
        PdfWord(x=45, y_bottom=710, y_top=124, text="19.06.2026"),
        PdfWord(x=102, y_bottom=710, y_top=124, text="04:02"),
        PdfWord(x=152, y_bottom=710, y_top=124, text="Перевод"),
        PdfWord(x=210, y_bottom=710, y_top=124, text="на"),
        PdfWord(x=230, y_bottom=710, y_top=124, text="карту"),
        PdfWord(x=427, y_bottom=710, y_top=124, text="+2 000,00"),
        PdfWord(x=525, y_bottom=710, y_top=124, text="10 415,15"),
        PdfWord(x=152, y_bottom=698, y_top=136, text="AUTOPLATEZH_P2P."),
        PdfWord(x=260, y_bottom=698, y_top=136, text="Операция"),
        PdfWord(x=320, y_bottom=698, y_top=136, text="по"),
        PdfWord(x=340, y_bottom=698, y_top=136, text="счету"),
        PdfWord(x=380, y_bottom=698, y_top=136, text="****0805"),
        PdfWord(x=45, y_bottom=680, y_top=152, text="18.06.2026"),
        PdfWord(x=152, y_bottom=680, y_top=152, text="Супермаркеты"),
        PdfWord(x=437, y_bottom=680, y_top=152, text="460,00"),
        PdfWord(x=529, y_bottom=680, y_top=152, text="3 415,15"),
        PdfWord(x=152, y_bottom=668, y_top=164, text="NORDIK."),
        PdfWord(x=210, y_bottom=668, y_top=164, text="Операция"),
        PdfWord(x=270, y_bottom=668, y_top=164, text="по"),
        PdfWord(x=290, y_bottom=668, y_top=164, text="карте"),
        PdfWord(x=330, y_bottom=668, y_top=164, text="****1"),
    ]
    out, stats = recover_operation_table_from_page_geometry(
        COLUMNS, matrix, ROLES, words
    )
    assert stats.rows_inserted == 1
    assert len(out) == 3
    assert out[1][2] == "+2 000,00"
    assert out[1][3] == "10 415,15"
    assert "Перевод" in out[1][1]
    assert "AUTOPLATEZH" in out[1][1]


def test_insert_spine_not_stolen_by_duplicate_amount_elsewhere():
    """Repeated amount values must claim by balance co-location, not first match."""
    matrix = [
        ["19.06.2026", "Додо Пицца. Операция по карте ****1", "2 721,00", "7 694,15"],
        # Same amount text later on the page — must not claim the missing spine glyph.
        ["12.06.2026", "Перевод AUTOPLATEZH. Операция по счёту ****1", "+2 000,00", "8 100,00"],
    ]
    words = [
        PdfWord(x=45, y_bottom=740, y_top=96, text="19.06.2026"),
        PdfWord(x=152, y_bottom=740, y_top=96, text="Додо"),
        PdfWord(x=430, y_bottom=740, y_top=96, text="2 721,00"),
        PdfWord(x=525, y_bottom=740, y_top=96, text="7 694,15"),
        # Missing from matrix (should be inserted)
        PdfWord(x=45, y_bottom=710, y_top=124, text="19.06.2026"),
        PdfWord(x=152, y_bottom=710, y_top=124, text="Перевод"),
        PdfWord(x=210, y_bottom=710, y_top=124, text="AUTOPLATEZH"),
        PdfWord(x=427, y_bottom=710, y_top=124, text="+2 000,00"),
        PdfWord(x=525, y_bottom=710, y_top=124, text="10 415,15"),
        # Present matrix row (later on page)
        PdfWord(x=45, y_bottom=500, y_top=400, text="12.06.2026"),
        PdfWord(x=152, y_bottom=500, y_top=400, text="Перевод"),
        PdfWord(x=210, y_bottom=500, y_top=400, text="AUTOPLATEZH"),
        PdfWord(x=427, y_bottom=500, y_top=400, text="+2 000,00"),
        PdfWord(x=525, y_bottom=500, y_top=400, text="8 100,00"),
    ]
    out, stats = recover_operation_table_from_page_geometry(
        COLUMNS, matrix, ROLES, words
    )
    assert stats.rows_inserted == 1
    assert len(out) == 3
    inserted = [r for r in out if "10 415,15" in r[3]]
    assert len(inserted) == 1
    assert inserted[0][2] == "+2 000,00"
    kept = [r for r in out if r[3] == "8 100,00"]
    assert len(kept) == 1
    assert kept[0][2] == "+2 000,00"


def test_reassign_amount_from_thin_head_to_body():
    """Money on duplicated thin category head → move onto merchant body on same spine."""
    matrix = [
        ["08.01.2026", "Прочие расходы REG.RU SAMARA RUS. Операция по карте ****6681", "", ""],
        ["09.01.2026", "Прочие расходы", "494,00", "0,00"],
        ["10.01.2026", "Оплата A. Операция по карте ****1", "10,00", "100,00"],
    ]
    words = [
        PdfWord(x=45, y_bottom=200, y_top=748, text="08.01.2026"),
        PdfWord(x=150, y_bottom=200, y_top=748, text="Прочие"),
        PdfWord(x=200, y_bottom=200, y_top=748, text="расходы"),
        PdfWord(x=437, y_bottom=200, y_top=748, text="494,00"),
        PdfWord(x=544, y_bottom=200, y_top=748, text="0,00"),
        PdfWord(x=150, y_bottom=190, y_top=759, text="REG.RU"),
        PdfWord(x=220, y_bottom=190, y_top=759, text="Операция"),
        PdfWord(x=280, y_bottom=190, y_top=759, text="по"),
        PdfWord(x=300, y_bottom=190, y_top=759, text="карте"),
        PdfWord(x=360, y_bottom=190, y_top=759, text="****6681"),
        PdfWord(x=45, y_bottom=150, y_top=800, text="10.01.2026"),
        PdfWord(x=150, y_bottom=150, y_top=800, text="Оплата"),
        PdfWord(x=437, y_bottom=150, y_top=800, text="10,00"),
        PdfWord(x=544, y_bottom=150, y_top=800, text="100,00"),
    ]
    out, stats = recover_operation_table_from_page_geometry(
        COLUMNS, matrix, ROLES, words
    )
    assert stats.amounts >= 1
    assert len(out) == 2
    body = next(r for r in out if "REG.RU" in r[1])
    assert body[2] == "494,00"
    assert body[3] == "0,00"
