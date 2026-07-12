"""Tests for geometry-aware Docling table extraction."""

from types import SimpleNamespace

from app.services.docling_table_geometry import (
    GeometryTable,
    PdfWord,
    geometry_table_to_markdown,
    matrix_from_docling_table,
    refine_geometry_table,
)
from app.services.table_schema_normalize import parse_markdown_pipe_table_schema


def _bbox(l, t, r, b):
    return SimpleNamespace(l=l, t=t, r=r, b=b)


def _cell(text, *, header=False, bbox=None):
    return SimpleNamespace(
        text=text,
        column_header=header,
        bbox=bbox,
        row_span=1,
        col_span=1,
    )


def test_matrix_from_docling_grid():
    grid = [
        [
            _cell("Дата", header=True),
            _cell("Сумма", header=True),
            _cell("Описание", header=True),
        ],
        [_cell("01.01.2024"), _cell("100"), _cell("A")],
        [_cell("02.01.2024"), _cell("200"), _cell("B")],
    ]
    table = SimpleNamespace(data=SimpleNamespace(grid=grid))
    parsed = matrix_from_docling_table(table)
    assert parsed is not None
    assert parsed.headers == ["Дата", "Сумма", "Описание"]
    assert len(parsed.rows) == 2


def test_refine_splits_wide_column_by_pdf_word_gaps():
    """Docling merged commission+description; PDF words keep separate X."""
    # 4 narrow + 1 wide column (like document.pdf ops table).
    col_boxes = {
        0: _bbox(20, 370, 66, 740),
        1: _bbox(70, 370, 124, 740),
        2: _bbox(136, 370, 199, 740),
        3: _bbox(213, 370, 269, 740),
        4: _bbox(285, 370, 485, 740),  # wide: commission + description
    }
    row_boxes = {
        0: _bbox(20, 370, 480, 386),  # header
        1: _bbox(20, 398, 485, 415),
        2: _bbox(20, 428, 458, 445),
        3: _bbox(20, 458, 449, 475),
        4: _bbox(20, 488, 458, 505),
    }
    header = [
        _cell("Дата и время операции", header=True),
        _cell("Дата обработки банком", header=True),
        _cell("Сумма операции валюте операции", header=True),
        _cell("Сумма в валюте карты", header=True),
        _cell("Комиссия Описание операции", header=True),
    ]
    data_rows = []
    for _ in range(4):
        data_rows.append(
            [
                _cell("09.07.2026"),
                _cell("11.07.2026"),
                _cell("0.0 RUB"),
                _cell("-139.9"),
                _cell("0.0 RUB Оплата товаров"),
            ]
        )
    grid = [header, *data_rows]

    def get_column_bounding_boxes():
        return col_boxes

    def get_row_bounding_boxes():
        return row_boxes

    table = SimpleNamespace(
        data=SimpleNamespace(
            grid=grid,
            get_column_bounding_boxes=get_column_bounding_boxes,
            get_row_bounding_boxes=get_row_bounding_boxes,
        )
    )

    words = [
        PdfWord(x=286.6, y_bottom=100, y_top=375, text="Комиссия"),
        PdfWord(x=414.4, y_bottom=100, y_top=375, text="Описание операции"),
    ]
    # Four data rows with commission @292 and description @322.
    for y_top in (405.0, 435.0, 465.0, 495.0):
        words.append(PdfWord(x=291.6, y_bottom=100, y_top=y_top, text="0.0 RUB"))
        words.append(
            PdfWord(x=322.0, y_bottom=100, y_top=y_top, text="Оплата товаров и услуг")
        )

    refined = refine_geometry_table(table, pdf_words=words)
    assert refined is not None
    assert refined.source == "docling_grid+pdf_geometry"
    assert len(refined.headers) == 6
    assert refined.headers[4] == "Комиссия"
    assert refined.headers[5] == "Описание операции"
    assert refined.rows[0][4] == "0.0 RUB"
    assert "Оплата" in refined.rows[0][5]
    assert "0.0 RUB" not in refined.rows[0][5]

    md = geometry_table_to_markdown(refined)
    parsed = parse_markdown_pipe_table_schema(md)
    assert parsed is not None
    assert len(parsed.columns) == 6
    assert parsed.columns[4] == "Комиссия"
    assert parsed.columns[5] == "Описание операции"


def test_refine_keeps_balanced_columns_unchanged():
    col_boxes = {
        0: _bbox(20, 100, 100, 400),
        1: _bbox(110, 100, 200, 400),
        2: _bbox(210, 100, 300, 400),
    }
    row_boxes = {
        0: _bbox(20, 100, 300, 120),
        1: _bbox(20, 130, 300, 150),
        2: _bbox(20, 160, 300, 180),
        3: _bbox(20, 190, 300, 210),
    }
    grid = [
        [
            _cell("Дата", header=True),
            _cell("Сумма", header=True),
            _cell("Описание", header=True),
        ],
        [_cell("1"), _cell("10"), _cell("A")],
        [_cell("2"), _cell("20"), _cell("B")],
        [_cell("3"), _cell("30"), _cell("C")],
    ]
    table = SimpleNamespace(
        data=SimpleNamespace(
            grid=grid,
            get_column_bounding_boxes=lambda: col_boxes,
            get_row_bounding_boxes=lambda: row_boxes,
        )
    )
    words = [
        PdfWord(x=30, y_bottom=0, y_top=140, text="1"),
        PdfWord(x=120, y_bottom=0, y_top=140, text="10"),
        PdfWord(x=220, y_bottom=0, y_top=140, text="A"),
    ]
    refined = refine_geometry_table(table, pdf_words=words)
    assert refined is not None
    assert refined.source == "docling_grid"
    assert refined.headers == ["Дата", "Сумма", "Описание"]
