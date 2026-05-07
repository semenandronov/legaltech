"""format_sources_for_prompt_with_docs: шапки [Документ Dd … чанк Cc] согласованы с retrieval-метками."""

from langchain_core.documents import Document

from app.services.rag_service import RAGService


def test_format_sources_for_prompt_with_docs_stops_early_and_lists_included_only():
    svc = object.__new__(RAGService)
    docs = [
        Document(
            page_content="A" * 400,
            metadata={"source_file": "one.txt", "file_id": "1"},
        ),
        Document(
            page_content="B" * 400,
            metadata={"source_file": "two.txt", "file_id": "2"},
        ),
    ]
    text, included = RAGService.format_sources_for_prompt_with_docs(
        svc, docs, max_context_chars=350
    )
    assert len(included) == 1
    assert included[0].metadata["source_file"] == "one.txt"
    assert "[Документ D1:" in text
    assert "чанк C1" in text
    assert "[Документ D2:" not in text


def test_format_sources_for_prompt_with_docs_all_fit():
    svc = object.__new__(RAGService)
    docs = [
        Document(page_content="short", metadata={"source_file": "a.txt", "file_id": "a"}),
        Document(page_content="also", metadata={"source_file": "b.txt", "file_id": "b"}),
    ]
    text, included = RAGService.format_sources_for_prompt_with_docs(
        svc, docs, max_context_chars=8000
    )
    assert len(included) == 2
    assert "[Документ D1:" in text and "[Документ D2:" in text
    assert "чанк C" in text
