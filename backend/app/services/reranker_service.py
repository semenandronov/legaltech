"""Reranker Service - cross-encoder reranking for RAG recall pools."""
from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

from langchain_core.documents import Document

from app.config import config
from app.services.chat.rag_passage_utils import passage_for_rerank

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import CrossEncoder

    CROSS_ENCODER_AVAILABLE = True
except ImportError:
    CROSS_ENCODER_AVAILABLE = False
    logger.warning("sentence-transformers not installed. Reranking will use fallback.")


class RerankerService:
    """Cross-encoder reranking for query–passage relevance."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        use_cohere: bool = False,
        cohere_api_key: Optional[str] = None,
        batch_size: int = 32,
        passage_max_chars: int = 2400,
    ):
        self.model_name = model_name
        self.use_cohere = use_cohere
        self.cohere_api_key = cohere_api_key
        self.batch_size = max(1, int(batch_size))
        self.passage_max_chars = max(256, int(passage_max_chars))

        self._cross_encoder = None
        self._cohere_client = None

        if use_cohere and cohere_api_key:
            try:
                import cohere

                self._cohere_client = cohere.Client(cohere_api_key)
                logger.info("Cohere reranker initialized (model=rerank-multilingual-v3.0)")
            except ImportError:
                logger.warning("Cohere not installed. Falling back to local cross-encoder.")
                self.use_cohere = False

        if CROSS_ENCODER_AVAILABLE and not self.use_cohere:
            try:
                self._cross_encoder = CrossEncoder(model_name)
                logger.info("Cross-encoder reranker initialized: %s", model_name)
            except Exception as e:
                logger.warning("Failed to load cross-encoder %s: %s", model_name, e)

    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_k: int = 10,
        score_threshold: Optional[float] = None,
        *,
        passage_max_chars: Optional[int] = None,
    ) -> List[Tuple[Document, float]]:
        if not documents:
            return []

        if self.use_cohere and self._cohere_client:
            return self._rerank_with_cohere(query, documents, top_k, score_threshold, passage_max_chars)
        if self._cross_encoder:
            return self._rerank_with_cross_encoder(
                query, documents, top_k, score_threshold, passage_max_chars
            )
        logger.warning("No reranker available, using fallback keyword scores")
        return self._fallback_rerank(query, documents, top_k)

    def _passage_text(self, doc: Document, passage_max_chars: Optional[int]) -> str:
        cap = passage_max_chars if passage_max_chars is not None else self.passage_max_chars
        return passage_for_rerank(doc, cap)

    def _rerank_with_cross_encoder(
        self,
        query: str,
        documents: List[Document],
        top_k: int,
        score_threshold: Optional[float],
        passage_max_chars: Optional[int],
    ) -> List[Tuple[Document, float]]:
        try:
            pairs = [
                [query, self._passage_text(doc, passage_max_chars)] for doc in documents
            ]
            scores = self._predict_batched(pairs)
            doc_scores = list(zip(documents, scores))
            doc_scores.sort(key=lambda x: float(x[1]), reverse=True)
            if score_threshold is not None:
                doc_scores = [
                    (doc, float(score))
                    for doc, score in doc_scores
                    if float(score) >= score_threshold
                ]
            result = [(doc, float(score)) for doc, score in doc_scores[:top_k]]
            logger.debug(
                "Cross-encoder reranked %s docs → %s (model=%s)",
                len(documents),
                len(result),
                self.model_name,
            )
            return result
        except Exception as e:
            logger.error("Cross-encoder reranking error: %s", e, exc_info=True)
            return self._fallback_rerank(query, documents, top_k)

    def _predict_batched(self, pairs: List[List[str]]) -> List[float]:
        if not self._cross_encoder:
            return [0.0] * len(pairs)
        bs = self.batch_size
        all_scores: List[float] = []
        for i in range(0, len(pairs), bs):
            chunk = pairs[i : i + bs]
            raw = self._cross_encoder.predict(chunk)
            all_scores.extend(float(x) for x in raw)
        return all_scores

    def _rerank_with_cohere(
        self,
        query: str,
        documents: List[Document],
        top_k: int,
        score_threshold: Optional[float],
        passage_max_chars: Optional[int],
    ) -> List[Tuple[Document, float]]:
        try:
            doc_texts = [self._passage_text(doc, passage_max_chars) for doc in documents]
            response = self._cohere_client.rerank(
                query=query,
                documents=doc_texts,
                top_n=min(top_k, len(documents)),
                model="rerank-multilingual-v3.0",
            )
            result = []
            for item in response.results:
                doc = documents[item.index]
                score = float(item.relevance_score)
                if score_threshold is None or score >= score_threshold:
                    result.append((doc, score))
            return result
        except Exception as e:
            logger.error("Cohere reranking error: %s", e)
            return self._fallback_rerank(query, documents, top_k)

    def _fallback_rerank(
        self,
        query: str,
        documents: List[Document],
        top_k: int,
    ) -> List[Tuple[Document, float]]:
        query_words = set(query.lower().split())
        doc_scores: List[Tuple[Document, float]] = []
        for doc in documents:
            content_words = set((doc.page_content or "").lower().split())
            intersection = len(query_words & content_words)
            union = len(query_words | content_words)
            jaccard = intersection / union if union > 0 else 0.0
            existing = doc.metadata.get("similarity_score", 0) if doc.metadata else 0
            try:
                existing_f = float(existing) if existing else 0.0
            except (TypeError, ValueError):
                existing_f = 0.0
            combined = (jaccard + existing_f) / 2 if existing_f else jaccard
            doc_scores.append((doc, combined))
        doc_scores.sort(key=lambda x: x[1], reverse=True)
        return doc_scores[:top_k]

    def rerank_to_documents(
        self,
        query: str,
        documents: List[Document],
        top_k: int = 10,
        score_threshold: Optional[float] = None,
        **kwargs: Any,
    ) -> List[Document]:
        ranked = self.rerank(query, documents, top_k, score_threshold, **kwargs)
        result = []
        for doc, score in ranked:
            md = dict(doc.metadata or {})
            md["rerank_score"] = float(score)
            doc.metadata = md
            result.append(doc)
        return result


_reranker: Optional[RerankerService] = None
_light_reranker: Optional[RerankerService] = None


def get_heavy_reranker_service() -> RerankerService:
    """Full cross-encoder (BGE / Cohere) for deep retrieval tiers."""
    global _reranker
    if _reranker is None:
        cohere_key = getattr(config, "COHERE_API_KEY", "") or ""
        use_cohere = bool(
            getattr(config, "CASE_ASSISTANT_RERANK_USE_COHERE", False)
            and cohere_key
        )
        model_name = getattr(config, "RERANKER_MODEL_NAME", "") or "BAAI/bge-reranker-v2-m3"
        batch_size = int(
            getattr(config, "CASE_ASSISTANT_RERANK_BATCH_SIZE", None)
            or getattr(config, "RERANKER_BATCH_SIZE", 32)
            or 32
        )
        max_chars = int(getattr(config, "CASE_ASSISTANT_RERANK_MAX_CHARS", 2400) or 2400)
        _reranker = RerankerService(
            model_name=model_name,
            use_cohere=use_cohere,
            cohere_api_key=cohere_key or None,
            batch_size=batch_size,
            passage_max_chars=max_chars,
        )
    return _reranker


def get_light_reranker_service() -> RerankerService:
    """Fast cross-encoder for instant/standard tiers."""
    global _light_reranker
    if _light_reranker is None:
        model_name = (
            getattr(config, "CASE_ASSISTANT_RERANK_LIGHT_MODEL", "")
            or "cross-encoder/ms-marco-MiniLM-L-6-v2"
        )
        batch_size = int(getattr(config, "CASE_ASSISTANT_RERANK_LIGHT_BATCH_SIZE", 64) or 64)
        max_chars = int(getattr(config, "CASE_ASSISTANT_RERANK_LIGHT_MAX_CHARS", 900) or 900)
        _light_reranker = RerankerService(
            model_name=model_name,
            use_cohere=False,
            batch_size=batch_size,
            passage_max_chars=max_chars,
        )
    return _light_reranker


def get_reranker_for_tier(rerank_tier: str) -> RerankerService:
    tier = (rerank_tier or "light").strip().lower()
    if tier == "heavy":
        return get_heavy_reranker_service()
    return get_light_reranker_service()


def get_reranker_service() -> RerankerService:
    """Backward-compatible default — heavy reranker."""
    return get_heavy_reranker_service()
