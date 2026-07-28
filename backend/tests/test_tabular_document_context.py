from langchain_core.documents import Document

from app.services.file_document_outline import build_outline_from_chunks, outline_payload_from_chunks


def test_build_outline_dedupes_section_roots():
    chunks = [
        Document(
            page_content="1. Subject",
            metadata={
                "chunk_level": "macro",
                "section_root_id": "sr1",
                "section_title": "SUBJECT",
                "section_number": "1",
                "char_start": 0,
                "char_end": 100,
            },
        ),
        Document(
            page_content="1.1 detail",
            metadata={
                "chunk_level": "micro",
                "section_root_id": "sr1",
                "section_title": "SUBJECT",
                "section_number": "1.1",
                "char_start": 10,
                "char_end": 80,
            },
        ),
        Document(
            page_content="2. Definitions",
            metadata={
                "chunk_level": "macro",
                "section_root_id": "sr2",
                "section_title": "DEFINITIONS",
                "section_number": "2",
                "char_start": 200,
                "char_end": 400,
            },
        ),
    ]
    outline, def_roots = build_outline_from_chunks(chunks)
    assert len(outline) == 2
    assert outline[0].section_root_id == "sr1"
    assert "sr2" in def_roots
    payload = outline_payload_from_chunks(chunks)
    assert len(payload["outline"]) == 2
    assert payload["index_fingerprint"]
