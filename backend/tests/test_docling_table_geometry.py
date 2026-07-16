"""Tests for geometry-aware Docling table extraction."""

from types import SimpleNamespace

from app.services.docling_table_geometry import (
    GeometryTable,
    PdfWord,
    geometry_table_to_markdown,
    matrix_from_docling_table,
    refine_geometry_table,
)
from app.services.legal_chunker import _Segment
from app.services.structured_table_indexer import StructuredTableIndexer
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


def test_parsed_pipe_table_from_geometry_skips_markdown():
    from app.services.table_schema_normalize import parsed_pipe_table_from_geometry

    parsed = parsed_pipe_table_from_geometry(
        ["Дата Операции (МСК)", "Категория", "Сумма В Валюте Счёта", "Остаток Средств"],
        [
            [
                "03.07.2024",
                "Супермаркеты PEKARNYA. Операция по карте ****6681 "
                "Перевод с карты Перевод для Ф. Операция по карте ****6681",
                "85,00",
                "5 531,58",
            ]
        ],
        source="docling_grid",
    )
    assert parsed is not None
    assert len(parsed.data_rows) == 2
    assert any(str(w).startswith("source:") for w in parsed.quality_warnings)
    assert parsed.data_rows[0][2] == "85,00"
    assert "Перевод" not in parsed.data_rows[0][1]
    assert "Перевод" in parsed.data_rows[1][1]


def test_shard_geometry_table_keeps_header():
    from app.services.docling_table_geometry import shard_geometry_table

    table = GeometryTable(
        headers=["A", "B"],
        rows=[["1", "x"], ["2", "y"], ["3", "z"], ["4", "w"]],
        source="docling_grid",
    )
    shards = shard_geometry_table(table, rows_per_group=2)
    assert len(shards) == 2
    assert shards[0].headers == ["A", "B"]
    assert len(shards[0].rows) == 2
    assert shards[1].rows[0][0] == "3"


def test_indexer_prefers_native_geometry_over_markdown(monkeypatch):
    monkeypatch.setattr(
        "app.services.structured_table_indexer._min_transaction_rows",
        lambda: 2,
    )
    geom = GeometryTable(
        headers=["Дата операции", "Сумма", "Описание"],
        rows=[
            ["10.01.2024", "-100,00", "A"],
            ["11.01.2024", "-50,00", "B"],
        ],
        source="docling_grid",
    )
    # Deliberately broken markdown that would fail/parse wrong if preferred.
    bad_md = "| broken |\n|---|\n| x |\n| y |\n"
    docs = StructuredTableIndexer().index(
        segments=[
            _Segment(
                text=bad_md,
                section_title="",
                section_number="",
                parent_path=[],
                page_no=1,
                char_start=0,
                char_end=10,
                is_table=True,
                table_geometry=geom,
            )
        ],
        full_text=bad_md,
        base_metadata={"doc_id": "d1", "case_id": "c1"},
        preseg_strategy="test",
        filename="stmt.pdf",
    )
    rows = [d for d in docs if d.metadata.get("chunk_level") == "row"]
    assert len(rows) == 2
    assert rows[0].metadata["row_columns"]["Описание"] == "A"
    assert rows[1].metadata["row_columns"]["Сумма"] == "-50,00"


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
