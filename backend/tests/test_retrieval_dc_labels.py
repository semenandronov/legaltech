"""compute_retrieval_dc_labels — без тяжёлых импортов."""

from langchain_core.documents import Document

from app.services.chat.retrieval_dc_labels import compute_retrieval_dc_labels


def test_dc_labels_two_files_distinct_d():
    docs = [
        Document(page_content="a", metadata={"file_id": "f1", "chunk_index": 3}),
        Document(page_content="b", metadata={"file_id": "f2", "chunk_index": 0}),
    ]
    assert compute_retrieval_dc_labels(docs) == [(1, 3), (2, 0)]


def test_dc_labels_same_file_uses_chunk_index_and_fallback():
    docs = [
        Document(page_content="a", metadata={"file_id": "f1", "chunk_index": 10}),
        Document(page_content="b", metadata={"file_id": "f1"}),
    ]
    assert compute_retrieval_dc_labels(docs) == [(1, 10), (1, 1)]
