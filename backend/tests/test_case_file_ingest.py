"""Case file ingest helpers."""
from __future__ import annotations

from app.services.case_file_ingest import (
    sanitize_upload_filename,
    unique_disk_path,
)


def test_sanitize_upload_filename_strips_path():
    assert sanitize_upload_filename("../../evil.pdf") == "evil.pdf"


def test_unique_disk_path_avoids_collision(tmp_path):
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "doc.pdf").write_bytes(b"x")
    path, name = unique_disk_path(str(case_dir), "doc.pdf")
    assert name == "doc (1).pdf"
    assert path.endswith("doc (1).pdf")
