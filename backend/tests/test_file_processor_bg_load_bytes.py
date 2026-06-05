"""file_processor_bg must read uploads from disk when file_content is NULL."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import file_processor_bg as fpb


def _file_row(**kwargs):
    defaults = dict(
        id="fid-1",
        filename="doc.pdf",
        file_path="case-1/doc.pdf",
        file_content=None,
        processing_status="pending",
        processing_started_at=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_process_one_file_loads_bytes_via_case_file_bytes_helper():
    file_row = _file_row()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = file_row

    with patch("app.services.case_file_bytes.load_case_file_bytes", return_value=b"%PDF-bytes") as load_bytes:
        with patch(
            "app.services.langchain_loaders.DocumentLoaderService.load_document",
            return_value=[],
        ):
            with patch.object(fpb, "_set_error") as set_error:
                fpb._process_one_file(db, "fid-1", "case-1", MagicMock())

    load_bytes.assert_called_once_with(file_row)
    set_error.assert_called_once()
    assert set_error.call_args[0][1] == "fid-1"


def test_process_one_file_errors_when_bytes_missing_everywhere():
    file_row = _file_row()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = file_row

    with patch("app.services.case_file_bytes.load_case_file_bytes", return_value=None):
        with patch.object(fpb, "_set_error") as set_error:
            fpb._process_one_file(db, "fid-1", "case-1", MagicMock())

    set_error.assert_called_once()
    assert "диске" in set_error.call_args[0][2]
    db.commit.assert_not_called()


def test_process_one_file_skips_cancelled_before_loading_bytes():
    file_row = _file_row(processing_status="cancelled")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = file_row

    with patch("app.services.case_file_bytes.load_case_file_bytes") as load_bytes:
        fpb._process_one_file(db, "fid-1", "case-1", MagicMock())

    load_bytes.assert_not_called()
