"""Case file bytes: disk-first load, optional DB blob on upload."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import case_file_bytes as cfb


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.case_file_bytes.config.UPLOAD_DIR", str(tmp_path))
    return tmp_path


def test_load_case_file_bytes_from_disk(upload_dir):
    case_id = "case-1"
    sub = upload_dir / case_id
    sub.mkdir()
    pdf = sub / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 disk")

    file_row = SimpleNamespace(
        id="f1",
        file_path=os.path.join(case_id, "doc.pdf"),
        file_content=None,
    )
    assert cfb.load_case_file_bytes(file_row) == b"%PDF-1.4 disk"


def test_load_case_file_bytes_db_fallback(upload_dir):
    file_row = SimpleNamespace(
        id="f2",
        file_path="missing/case/x.pdf",
        file_content=b"legacy-bytes",
    )
    assert cfb.load_case_file_bytes(file_row) == b"legacy-bytes"


def test_load_case_file_bytes_missing(upload_dir):
    file_row = SimpleNamespace(id="f3", file_path=None, file_content=None)
    assert cfb.load_case_file_bytes(file_row) is None


def test_case_file_content_for_db_respects_flag():
    with patch.object(cfb.config, "FILE_STORE_BYTES_IN_DB", False):
        assert cfb.case_file_content_for_db(b"x") is None
    with patch.object(cfb.config, "FILE_STORE_BYTES_IN_DB", True):
        assert cfb.case_file_content_for_db(b"x") == b"x"
