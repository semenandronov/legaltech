"""Unit tests for checklist file import parsing."""

import pytest

from app.services.tabular_checklist_import import (
    parse_checklist_csv,
    parse_checklist_file,
    parse_checklist_text,
    questions_text_from_items,
)


def test_parse_numbered_and_bulleted_text():
    text = """
    Чек-лист DD
    1. Есть ли право на субаренду?
    2) Каков срок договора?
    - Применимое право
    * Штрафные санкции
    """
    items = parse_checklist_text(text)
    assert "Есть ли право на субаренду?" in items
    assert "Каков срок договора?" in items
    assert "Применимое право" in items
    assert "Штрафные санкции" in items
    assert "Чек-лист DD" in items  # plain title-like line kept as item


def test_parse_csv_skips_header():
    data = "вопрос\nЕсть ли опцион?\nСрок уведомления\n".encode("utf-8")
    items = parse_checklist_csv(data)
    assert items == ["Есть ли опцион?", "Срок уведомления"]


def test_parse_checklist_file_txt_and_limit():
    items = parse_checklist_file(
        filename="list.md",
        data="# DD\n1. Первый вопрос\n2. Второй вопрос\n".encode("utf-8"),
    )
    assert items == ["Первый вопрос", "Второй вопрос"]
    assert questions_text_from_items(items).startswith("1. Первый вопрос")

    with pytest.raises(ValueError, match="Unsupported"):
        parse_checklist_file(filename="x.pdf", data=b"abc")

    with pytest.raises(ValueError, match="empty"):
        parse_checklist_file(filename="x.txt", data=b"")
