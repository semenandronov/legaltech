"""Structured file text + editor attach context."""
from types import SimpleNamespace

from langchain_core.documents import Document

from app.services.structured_file_text import (
    build_editor_attached_files_context,
    cap_structured_text,
    structured_text_from_indexed_documents,
)


def test_structured_text_from_macro_chunks():
    docs = [
        Document(
            page_content="Текст раздела один.",
            metadata={
                "chunk_level": "macro",
                "char_start": 0,
                "section_title": "Раздел 1",
            },
        ),
        Document(
            page_content="Текст раздела два.",
            metadata={
                "chunk_level": "macro",
                "char_start": 100,
                "section_title": "Раздел 2",
            },
        ),
    ]
    text, fmt = structured_text_from_indexed_documents(docs)
    assert fmt == "markdown"
    assert "## Раздел 1" in text
    assert "Текст раздела один" in text
    assert "## Раздел 2" in text


def test_cap_structured_text():
    out = cap_structured_text("abcdef", 4)
    assert len(out) <= 4 + 50
    assert "обрезан" in out


def test_build_editor_attached_files_context_filters_foreign_case(monkeypatch):
    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return SimpleNamespace(id="case-1", user_id="u1")

        def all(self):
            return [
                SimpleNamespace(
                    id="f1",
                    filename="a.pdf",
                    structured_text="Содержимое A",
                    structured_text_format="markdown",
                    original_text="",
                )
            ]

    class FakeDb:
        def query(self, model):
            return FakeQuery()

    ctx = build_editor_attached_files_context(
        FakeDb(),
        case_id="case-1",
        user_id="u1",
        file_ids=["f1"],
    )
    assert "ПРИКРЕПЛЁННЫЙ ДОКУМЕНТ" in ctx
    assert "Содержимое A" in ctx
