"""Unit tests for Content-Disposition helpers."""

from app.utils.content_disposition import content_disposition_attachment, sanitize_attachment_filename


def test_sanitize_strips_path_and_unsafe_chars():
    assert sanitize_attachment_filename("../../a/b<c>.xlsx") == "b_c_.xlsx"
    assert sanitize_attachment_filename("  ") == "export"


def test_content_disposition_includes_utf8_filename_star():
    header = content_disposition_attachment("Выписка Сбер.xlsx")
    assert 'filename="' in header
    assert "filename*=UTF-8''" in header
    assert ".xlsx" in header
