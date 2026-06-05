"""Google Drive import: filename resolution and download plans."""
from __future__ import annotations

import pytest

from app.services.google_drive_import_service import (
    DriveFileRef,
    build_download_plan,
    resolve_output_filename,
)


def test_resolve_google_doc_to_pdf():
    name = resolve_output_filename("Претензия", "application/vnd.google-apps.document")
    assert name.endswith(".pdf")


def test_resolve_spreadsheet_to_xlsx():
    name = resolve_output_filename("Расчёт", "application/vnd.google-apps.spreadsheet")
    assert name.endswith(".xlsx")


def test_build_download_plan_export():
    ref = DriveFileRef(id="abc", name="Doc", mime_type="application/vnd.google-apps.document")
    plan = build_download_plan(ref)
    assert plan.export_mime == "application/pdf"
    assert plan.output_filename.endswith(".pdf")


def test_build_download_plan_binary_pdf():
    ref = DriveFileRef(id="x", name="scan.pdf", mime_type="application/pdf")
    plan = build_download_plan(ref)
    assert plan.export_mime is None
    assert plan.output_filename == "scan.pdf"


def test_unsupported_mime_raises():
    ref = DriveFileRef(id="x", name="video.mp4", mime_type="video/mp4")
    with pytest.raises(ValueError, match="неподдерживаемый"):
        build_download_plan(ref)
