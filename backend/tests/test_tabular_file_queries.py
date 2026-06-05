"""Tabular file queries must not load PDF blobs."""
from unittest.mock import MagicMock

from app.services.tabular_file_queries import (
    _EXTRACTION_FILE_ATTRS,
    _TABLE_FILE_ATTRS,
    query_files_for_table,
)


def test_table_query_applies_load_only():
    db = MagicMock()
    chain = MagicMock()
    db.query.return_value = chain
    chain.filter.return_value = chain
    query_files_for_table(db, "case-1")
    chain.options.assert_called_once()


def test_table_attrs_exclude_blobs():
    loaded = {a.key for a in _TABLE_FILE_ATTRS}
    assert "file_content" not in loaded
    assert "html_content" not in loaded
    assert "original_text" not in loaded
    assert "id" in loaded
    assert "filename" in loaded


def test_extraction_attrs_exclude_blobs():
    loaded = {a.key for a in _EXTRACTION_FILE_ATTRS}
    assert "file_content" not in loaded
    assert "html_content" not in loaded
    assert "id" in loaded
    assert "original_text" in loaded
