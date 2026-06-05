"""RerankerService unit tests (no model download)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.services.reranker_service import RerankerService


def test_fallback_rerank_prefers_query_overlap():
    svc = RerankerService(model_name="test-model")
    svc._cross_encoder = None
    svc.use_cohere = False
    docs = [
        Document(page_content="договор неустойка поставка", metadata={}),
        Document(page_content="исковое заявление суд", metadata={}),
    ]
    ranked = svc.rerank("неустойка договор", docs, top_k=1)
    assert len(ranked) == 1
    assert "неустойка" in ranked[0][0].page_content


def test_cross_encoder_reorders_documents():
    svc = RerankerService(model_name="BAAI/bge-reranker-v2-m3")
    mock_encoder = MagicMock()
    mock_encoder.predict.side_effect = lambda pairs: [0.1, 0.9][: len(pairs)]
    svc._cross_encoder = mock_encoder

    docs = [
        Document(page_content="low relevance"),
        Document(page_content="high relevance"),
    ]
    ranked = svc.rerank("query", docs, top_k=2)
    assert ranked[0][0].page_content == "high relevance"
    assert ranked[0][1] > ranked[1][1]


def test_predict_batched_chunks_pairs():
    svc = RerankerService(model_name="test", batch_size=2)
    mock_encoder = MagicMock()
    mock_encoder.predict.side_effect = [
        [0.5, 0.6],
        [0.7],
    ]
    svc._cross_encoder = mock_encoder
    pairs = [["q", "a"], ["q", "b"], ["q", "c"]]
    scores = svc._predict_batched(pairs)
    assert len(scores) == 3
    assert mock_encoder.predict.call_count == 2


@patch("app.services.reranker_service.CROSS_ENCODER_AVAILABLE", False)
def test_get_reranker_service_singleton_without_sentence_transformers():
    import app.services.reranker_service as mod

    mod._reranker = None
    svc1 = mod.get_reranker_service()
    svc2 = mod.get_reranker_service()
    assert svc1 is svc2
    assert svc1._cross_encoder is None
