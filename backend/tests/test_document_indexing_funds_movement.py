"""Integration: funds_movement.pdf → structured table chunks."""

from pathlib import Path

import pytest

from app.services.document_indexing import build_index_chunks

PDF_PATH = Path("/Users/semyon_andronov04/Downloads/funds_movement.pdf")


@pytest.mark.skipif(not PDF_PATH.is_file(), reason="funds_movement.pdf not available locally")
def test_funds_movement_indexes_as_row_chunks():
    pdf_bytes = PDF_PATH.read_bytes()
    docs = build_index_chunks(
        content_bytes=pdf_bytes,
        filename="funds_movement.pdf",
        base_metadata={"doc_id": "test", "file_id": "test", "case_id": "case-test"},
        loader_native_text=True,
    )

    rows = [d for d in docs if d.metadata.get("chunk_level") == "row"]
    preambles = [d for d in docs if d.metadata.get("chunk_level") == "preamble"]

    assert len(rows) >= 300
    assert len(preambles) >= 1
    assert all(d.metadata.get("index_profile") == "structured_table" for d in docs)
    assert not any(d.metadata.get("chunk_level") == "macro" for d in docs)
    assert not any(d.metadata.get("chunk_level") == "micro" for d in docs)

    global_indices = [d.metadata.get("global_row_index") for d in rows]
    assert global_indices == list(range(len(rows)))

    yandex_hits = [d for d in rows if "YANDEX" in (d.page_content or "").upper()]
    assert yandex_hits, "expected at least one Yandex operation row chunk"
