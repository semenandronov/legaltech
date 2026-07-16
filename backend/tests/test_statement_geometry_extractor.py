"""Unit tests for geometry-first statement extraction (no Docling)."""

from __future__ import annotations

from app.services.docling_table_geometry import PdfWord
from app.services.statement_geometry_extractor import (
    ColumnLayout,
    cluster_lines,
    extract_operations_from_page,
    learn_column_layout,
)
from app.services.statement_geometry_indexer import (
    should_try_statement_geometry,
    _quality_accept,
)


def _w(text: str, x: float, y: float) -> PdfWord:
    return PdfWord(x=x, y_bottom=800.0 - y, y_top=y, text=text)


def test_cluster_lines_groups_by_y():
    words = [
        _w("01.02.2024", 50, 100),
        _w("Coffee", 120, 100.5),
        _w("100,00", 400, 100.2),
        _w("02.02.2024", 50, 120),
        _w("Shop", 120, 120),
        _w("50,00", 400, 120),
    ]
    lines = cluster_lines(words)
    assert len(lines) == 2
    assert "01.02.2024" in lines[0].text
    assert "02.02.2024" in lines[1].text


def test_learn_layout_and_split_adjacent_ops():
    """Two neighboring ops must not glue category text (the classic Docling failure)."""
    words = []
    # Op A — transport
    y1 = 200.0
    words += [
        _w("30.07.2024", 48, y1),
        _w("Транспорт", 140, y1),
        _w("bilet.nspk.ru", 210, y1),
        _w("65,00", 420, y1),
        _w("5 741,92", 500, y1),
    ]
    # Op B — supermarket on the next visual line
    y2 = 218.0
    words += [
        _w("30.07.2024", 48, y2),
        _w("Супермаркеты", 140, y2),
        _w("VKUSTER", 230, y2),
        _w("1 000,00", 420, y2),
        _w("4 741,92", 500, y2),
    ]
    # Extra data lines so layout learns stably
    for i in range(4):
        y = 240.0 + i * 16
        words += [
            _w(f"0{i+1}.07.2024", 48, y),
            _w("Покупка", 140, y),
            _w("MERCHANT", 220, y),
            _w(f"{10+i}0,00", 420, y),
            _w(f"{1000+i},00", 500, y),
        ]

    lines = cluster_lines(words)
    layout = learn_column_layout(lines, page_width=595.0)
    assert layout is not None
    assert layout.amount_x is not None
    assert layout.balance_x is not None

    ops = extract_operations_from_page(lines, layout=layout, page_no=1)
    assert len(ops) >= 2
    first_two = ops[:2]
    texts = [op.category_text for op in first_two]
    assert any("Транспорт" in t and "VKUSTER" not in t for t in texts)
    assert any("VKUSTER" in t and "bilet" not in t.lower() for t in texts)
    amounts = {op.amount_raw.replace(" ", "") for op in first_two}
    assert "65,00" in amounts or "65.00" in amounts
    assert any("1000" in a.replace(" ", "").replace("\u00a0", "") for a in amounts)


def test_multiline_description_attaches_without_new_date():
    layout = ColumnLayout(
        date_x=50,
        amount_x=420,
        balance_x=500,
        desc_x0=80,
        desc_x1=390,
        page_width=595,
    )
    words = [
        # money spine
        _w("10.01.2026", 50, 100),
        _w("12:30", 95, 100),
        _w("Перевод", 140, 100),
        _w("+2 000,00", 420, 100),
        _w("10 000,00", 500, 100),
        # body continuation — may repeat date (posting) but has no money
        _w("10.01.2026", 50, 114),
        _w("123456", 110, 114),
        _w("Перевод", 140, 114),
        _w("от", 190, 114),
        _w("Иванов", 230, 114),
        # next money spine
        _w("11.01.2026", 50, 130),
        _w("Кафе", 140, 130),
        _w("300,00", 420, 130),
        _w("9 700,00", 500, 130),
    ]
    lines = cluster_lines(words)
    ops = extract_operations_from_page(lines, layout=layout, page_no=2)
    assert len(ops) == 2
    assert "Иванов" in ops[0].category_text
    assert "Кафе" in ops[1].category_text
    assert "Иванов" not in ops[1].category_text


def test_money_spine_does_not_split_on_body_date():
    """Body line with a date but no money must not open a second operation."""
    layout = ColumnLayout(
        date_x=50,
        amount_x=420,
        balance_x=500,
        desc_x0=80,
        desc_x1=390,
        page_width=595,
    )
    words = [
        _w("30.07.2024", 50, 100),
        _w("00:15", 95, 100),
        _w("Транспорт", 140, 100),
        _w("65,00", 420, 100),
        _w("5 741,92", 500, 100),
        _w("31.07.2024", 50, 112),
        _w("242234", 110, 112),
        _w("bilet.nspk.ru", 170, 112),
        _w("****6681", 140, 124),
        _w("30.07.2024", 50, 140),
        _w("Супермаркеты", 140, 140),
        _w("229,90", 420, 140),
        _w("5 806,92", 500, 140),
        _w("30.07.2024", 50, 152),
        _w("VKUSTER", 170, 152),
    ]
    lines = cluster_lines(words)
    ops = extract_operations_from_page(lines, layout=layout, page_no=1)
    assert len(ops) == 2
    assert "bilet" in ops[0].category_text.lower()
    assert "VKUSTER" not in ops[0].category_text
    assert "VKUSTER" in ops[1].category_text
    assert "65" in ops[0].amount_raw.replace(" ", "")
    assert "229" in ops[1].amount_raw.replace(" ", "")


def test_page_chrome_not_appended_to_description():
    from app.services.statement_geometry_extractor import strip_statement_page_chrome

    layout = ColumnLayout(
        date_x=50,
        amount_x=420,
        balance_x=500,
        desc_x0=80,
        desc_x1=390,
        page_width=595,
    )
    words = [
        _w("05.07.2026", 50, 100),
        _w("Перевод", 140, 100),
        _w("на", 200, 100),
        _w("карту", 230, 100),
        _w("Андрей", 280, 100),
        _w("5 000,00", 420, 100),
        _w("1 000,00", 500, 100),
        _w("Продолжение", 140, 118),
        _w("на", 220, 118),
        _w("следующей", 250, 118),
        _w("странице", 320, 118),
        _w("Для", 140, 132),
        _w("проверки", 180, 132),
        _w("подлинности", 250, 132),
        _w("05.07.2026", 50, 150),
        _w("Кафе", 140, 150),
        _w("100,00", 420, 150),
        _w("900,00", 500, 150),
    ]
    lines = cluster_lines(words)
    ops = extract_operations_from_page(lines, layout=layout, page_no=1)
    assert len(ops) == 2
    assert "Андрей" in ops[0].category_text
    assert "Продолжение" not in ops[0].category_text
    assert "подлинности" not in ops[0].category_text
    assert "Кафе" in ops[1].category_text

    glued = (
        "Перевод на карту Андрей. Операция по карте "
        "Продолжение на следующей странице Для проверки подлинности"
    )
    cleaned = strip_statement_page_chrome(glued)
    assert "Андрей" in cleaned
    assert "Продолжение" not in cleaned

    verify_block = (
        "Перевод на карту. Операция по карте "
        "1. Зайдите в приложение Банк Онлайн в раздел «Выписки и справки» "
        "2. Нажмите кнопку и отсканируйте QR-код* "
        "Предоставляя QR-код третьим лицам, вы соглашаетесь"
    )
    cleaned2 = strip_statement_page_chrome(verify_block)
    assert "Перевод на карту" in cleaned2
    assert "Зайдите" not in cleaned2
    assert "QR-код третьим" not in cleaned2


def test_should_try_geometry_gates():
    assert (
        should_try_statement_geometry(
            filename="a.pdf",
            doc_type="bank_statement",
            loader_native_text=True,
            loader_did_ocr=False,
            content_bytes=b"%PDF",
        )
        is True
    )
    assert (
        should_try_statement_geometry(
            filename="a.pdf",
            doc_type="bank_statement",
            loader_native_text=True,
            loader_did_ocr=True,
            content_bytes=b"%PDF",
        )
        is False
    )
    assert (
        should_try_statement_geometry(
            filename="contract.docx",
            doc_type="bank_statement",
            loader_native_text=True,
            loader_did_ocr=False,
            content_bytes=b"xx",
        )
        is False
    )


def test_quality_accept_thresholds():
    assert _quality_accept(row_count=100, with_amount=90, with_date=95) is None
    assert _quality_accept(row_count=5, with_amount=5, with_date=5) is not None
    assert _quality_accept(row_count=100, with_amount=50, with_date=99) is not None
