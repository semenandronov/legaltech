"""Тесты вырезания утечек JSON answer_blocks из текста ответа."""

from app.services.chat.response_sanitize import strip_llm_answer_leaks


def test_strip_trailing_blocks_json():
    raw = (
        'Текст ответа [D1:C8].\n\n{"blocks": [\n{"block_id": "a", "markdown_text": "x", "citation_ids": []}\n]}'
    )
    out = strip_llm_answer_leaks(raw)
    assert '{"blocks"' not in out
    assert "Текст ответа" in out
    assert "[D1:C8]" in out


def test_strip_no_newline_before_brace():
    raw = '…в чанке C8.{"blocks": []}'
    out = strip_llm_answer_leaks(raw)
    assert "blocks" not in out.lower()
    assert "чанке C8" in out


def test_strip_fenced_json_blocks():
    raw = "Ответ.\n```json\n{\"blocks\": []}\n```\nХвост"
    out = strip_llm_answer_leaks(raw)
    assert "```" not in out
    assert "blocks" not in out.lower()


def test_passthrough_clean():
    t = "Краткий ответ по делу [D1:C0]."
    assert strip_llm_answer_leaks(t) == t


def test_strip_embedded_blocks_json_keeps_trailing_text():
    raw = (
        'Вступление.\n{"blocks": [\n  {"block_id": "a", "markdown_text": "x", "citation_ids": []}\n]}\n'
        "Продолжение после JSON."
    )
    out = strip_llm_answer_leaks(raw)
    assert '{"blocks"' not in out
    assert "Вступление" in out
    assert "Продолжение после JSON" in out
