"""Tests for case assistant Langfuse tracing helpers."""
from __future__ import annotations

from langchain_core.documents import Document

from app.services.observability.case_assistant_langfuse_tracing import (
    summarize_case_documents,
    summarize_metadata_filter,
)


def test_summarize_metadata_filter_merges_file_ids():
    flt = summarize_metadata_filter({"chunk_level": "micro"}, file_ids=["a", "b"])
    assert flt["chunk_level"] == "micro"
    assert flt["file_id"] == ["a", "b"]


def test_summarize_case_documents_counts_files_and_levels():
    docs = [
        Document(
            page_content="x",
            metadata={
                "file_id": "f1",
                "source_file": "contract.pdf",
                "chunk_level": "macro",
            },
        ),
        Document(
            page_content="y",
            metadata={
                "file_id": "f1",
                "source_file": "contract.pdf",
                "chunk_level": "micro",
            },
        ),
    ]
    summary = summarize_case_documents(docs)
    assert summary["docs_count"] == 2
    assert summary["unique_files"] == 1
    assert summary["chunk_levels"]["macro"] == 1
    assert summary["chunk_levels"]["micro"] == 1
