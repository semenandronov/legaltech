"""Тесты аккуратной склейки строк только с [N] в structured citations."""

from app.services.rag_service import merge_standalone_bracket_lines


def test_merge_keeps_markdown_header_with_blank_lines():
    text = "**I.\n\nИдентификация фактов**\n\nТекст тезиса.\n\n[1]"
    out = merge_standalone_bracket_lines(text)
    assert "**I." in out
    assert "Идентификация фактов" in out
    assert "Текст тезиса." in out
    assert "[1]" in out
    assert "Текст тезиса.[1]" in out or "Текст тезиса. [1]" in out


def test_merge_does_not_strip_newline_before_heading():
    text = "## Заголовок\n\n[2]"
    out = merge_standalone_bracket_lines(text)
    assert "## Заголовок" in out
    assert "[2]" in out


def test_multiple_citations_on_orphan_line():
    text = "Факт один.\n\n[1] [2]"
    out = merge_standalone_bracket_lines(text)
    assert "[1]" in out and "[2]" in out
