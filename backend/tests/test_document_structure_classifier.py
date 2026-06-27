"""Tests for document structure classification."""

from app.services.document_structure_classifier import classify_indexing_strategy
from app.services.legal_chunker import _Segment


def _table_segment(text: str, *, chars: int | None = None) -> _Segment:
    body = text if chars is None else text[:chars]
    return _Segment(
        text=body + "\n\n",
        section_title="",
        section_number="",
        parent_path=[],
        page_no=1,
        char_start=0,
        char_end=len(body) + 2,
        is_table=True,
    )


def _text_segment(text: str) -> _Segment:
    body = text + "\n\n"
    return _Segment(
        text=body,
        section_title="Header",
        section_number="",
        parent_path=[],
        page_no=1,
        char_start=0,
        char_end=len(body),
        is_heading=True,
    )


_SAMPLE_TABLE = """\
| Дата | Сумма | Описание |
|------|-------|----------|
| 01.01.2026 | -100 ₽ | Покупка |
| 02.01.2026 | +200 ₽ | Пополнение |
| 03.01.2026 | -50 ₽ | Кафе |
| 04.01.2026 | -30 ₽ | Такси |
| 05.01.2026 | -10 ₽ | Метро |
| 06.01.2026 | -20 ₽ | Магазин |
| 07.01.2026 | -40 ₽ | Аптека |
| 08.01.2026 | -60 ₽ | Бензин |
"""


def test_classify_bank_statement_doc_type():
    segments = [_text_segment("Шапка"), _table_segment(_SAMPLE_TABLE)]
    full_text = "".join(s.text for s in segments)
    assert (
        classify_indexing_strategy(
            segments, full_text=full_text, doc_type="bank_statement"
        )
        == "structured_table"
    )


def test_classify_table_dominant_document():
    segments = [_text_segment("Короткая шапка"), _table_segment(_SAMPLE_TABLE * 3)]
    full_text = "".join(s.text for s in segments)
    assert classify_indexing_strategy(segments, full_text=full_text) == "structured_table"


def test_classify_narrative_contract():
    segments = [
        _text_segment("Статья 1. Предмет договора\n\nИсполнитель обязуется..."),
        _text_segment("Статья 2. Сроки\n\nСрок действия..."),
    ]
    full_text = "".join(s.text for s in segments)
    assert classify_indexing_strategy(segments, full_text=full_text) == "narrative"
