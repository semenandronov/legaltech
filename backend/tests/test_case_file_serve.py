"""Serving case file originals: disk-first via load_case_file_bytes."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services import case_file_serve as cfs


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.case_file_bytes.config.UPLOAD_DIR", str(tmp_path))
    return tmp_path


def test_case_file_bytes_response_from_disk(upload_dir):
    case_id = "c1"
    (upload_dir / case_id).mkdir()
    (upload_dir / case_id / "a.pdf").write_bytes(b"%PDF-1.4")

    row = SimpleNamespace(
        id="fid",
        filename="a.pdf",
        file_type="pdf",
        file_path=f"{case_id}/a.pdf",
        file_content=None,
        original_text="not used",
    )
    resp = cfs.case_file_bytes_response(row, inline=True)
    assert resp.body == b"%PDF-1.4"
    assert resp.media_type == "application/pdf"
    assert resp.headers.get("X-Case-File-Source") == "original"


def test_pdf_missing_raises_404(upload_dir):
    row = SimpleNamespace(
        id="fid",
        filename="gone.pdf",
        file_type="pdf",
        file_path="c1/gone.pdf",
        file_content=None,
        original_text="extracted only",
    )
    with pytest.raises(HTTPException) as exc:
        cfs.load_case_original_bytes(row)
    assert exc.value.status_code == 404


def test_text_fallback_when_no_bytes(upload_dir):
    row = SimpleNamespace(
        id="fid",
        filename="note.txt",
        file_type="txt",
        file_path=None,
        file_content=None,
        original_text="hello",
    )
    resp = cfs.case_file_text_fallback_response(row, inline=True)
    assert resp.body == b"hello"
    assert resp.headers.get("X-Case-File-Source") == "extracted-text"
