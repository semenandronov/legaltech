"""Reranker Service - Phase 1.3 Implementation

This module provides cross-encoder reranking for RAG results
to improve relevance scoring beyond vector similarity.

Features:
- Cross-encoder reranking using sentence-transformers
- Cohere reranker integration (optional)
- Local lightweight cross-encoder fallback
- Score normalization
"""
from typing import List, Dict, Any, Optional, Tuple
from langchain_core.documents import Document
from app.config import config
import logging

logger = logging.getLogger(__name__)

# Try to import cross-encoder
try:
    from sentence_transformers import CrossEncoder
    CROSS_ENCODER_AVAILABLE = True
except ImportError:
    CROSS_ENCODER_AVAILABLE = False
    logger.warning("sentence-transformers not installed. Reranking will use fallback.")


class RerankerService:
    """
    Cross-encoder reranking service for improving RAG relevance.
    
    Reranks retrieved documents by computing a relevance score
    for each query-document pair using a cross-encoder model.
    """
    
    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        use_cohere: bool = False,
        cohere_api_key: Optional[str] = None
    ):
        """
        Initialize the reranker service.
        
        Args:
            model_name: Name of the cross-encoder model to use
            use_cohere: Whether to use Cohere reranker (requires API key)
            cohere_api_key: Cohere API key for reranking
        """
        self.model_name = model_name
        self.use_cohere = use_cohere
        self.cohere_api_key = cohere_api_key
        
        self._cross_encoder = None
        self._cohere_client = None
        
        # Initialize Cohere if requested
        if use_cohere and cohere_api_key:
            try:
                import cohere
                self._cohere_client = cohere.Client(cohere_api_key)
                logger.info("✅ Cohere reranker initialized")
            except ImportError:
                logger.warning("Cohere not installed. Falling back to local cross-encoder.")
                self.use_cohere = False
        
        # Initialize cross-encoder as fallback or primary
        if CROSS_ENCODER_AVAILABLE and not self.use_cohere:
            try:
                self._cross_encoder = CrossEncoder(model_name)
                logger.info(f"✅ Cross-encoder reranker initialized: {model_name}")
            except Exception as e:
                logger.warning(f"Failed to load cross-encoder: {e}")
    
    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_k: int = 10,
        score_threshold: Optional[float] = None
    ) -> List[Tuple[Document, float]]:
        """
        Rerank documents by relevance to query.
        
        Args:
            query: The search query
            documents: List of documents to rerank
            top_k: Number of top documents to return
            score_threshold: Minimum score threshold (optional)
            
        Returns:
            List of (document, score) tuples sorted by relevance
        """
        if not documents:
            return []
        
        if self.use_cohere and self._cohere_client:
            return self._rerank_with_cohere(query, documents, top_k, score_threshold)
        elif self._cross_encoder:
            return self._rerank_with_cross_encoder(query, documents, top_k, score_threshold)
        else:
            # Fallback: return original documents with default scores
            logger.warning("No reranker available, returning documents with default scores")
            return self._fallback_rerank(query, documents, top_k)
    
    def _rerank_with_cross_encoder(
        self,
        query: str,
        documents: List[Document],
        top_k: int,
        score_threshold: Optional[float]
    ) -> List[Tuple[Document, float]]:
        """Rerank using local cross-encoder model."""
        try:
            # Prepare pairs for cross-encoder
            pairs = [[query, doc.page_content] for doc in documents]
            
            # Get scores
            scores = self._cross_encoder.predict(pairs)
            
            # Combine documents with scores
            doc_scores = list(zip(documents, scores))
            
            # Sort by score (descending)
            doc_scores.sort(key=lambda x: x[1], reverse=True)
            
            # Apply threshold if specified
            if score_threshold is not None:
                doc_scores = [(doc, score) for doc, score in doc_scores if score >= score_threshold]
            
            # Return top_k
            result = doc_scores[:top_k]
            
            logger.debug(f"Reranked {len(documents)} docs → {len(result)} top results")
            return result
            
        except Exception as e:
            logger.error(f"Cross-encoder reranking error: {e}")
            return self._fallback_rerank(query, documents, top_k)
    
    def _rerank_with_cohere(
        self,
        query: str,
        documents: List[Document],
        top_k: int,
        score_threshold: Optional[float]
    ) -> List[Tuple[Document, float]]:
        """Rerank using Cohere API."""
        try:
            # Extract document texts
            doc_texts = [doc.page_content for doc in documents]
            
            # Call Cohere rerank API
            response = self._cohere_client.rerank(
                query=query,
                documents=doc_texts,
                top_n=top_k,
                model="rerank-multilingual-v3.0"  # Use multilingual for Russian support
            )
            
            # Build result list
            result = []
            for item in response.results:
                doc = documents[item.index]
                score = item.relevance_score
                
                if score_threshold is None or score >= score_threshold:
                    result.append((doc, score))
            
            logger.debug(f"Cohere reranked {len(documents)} docs → {len(result)} top results")
            return result
            
        except Exception as e:
            logger.error(f"Cohere reranking error: {e}")
            return self._fallback_rerank(query, documents, top_k)
    
    def _fallback_rerank(
        self,
        query: str,
        documents: List[Document],
        top_k: int
    ) -> List[Tuple[Document, float]]:
        """
        Fallback reranking using simple text similarity.
        
        Uses keyword overlap and length normalization.
        """
        query_words = set(query.lower().split())
        
        doc_scores = []
        for doc in documents:
            content_words = set(doc.page_content.lower().split())
            
            # Calculate Jaccard similarity
            intersection = len(query_words & content_words)
            union = len(query_words | content_words)
            jaccard = intersection / union if union > 0 else 0
            
            # Consider existing similarity score
            existing_score = doc.metadata.get("similarity_score", 0)
            if existing_score:
                combined_score = (jaccard + existing_score) / 2
            else:
                combined_score = jaccard
            
            doc_scores.append((doc, combined_score))
        
        # Sort by score
        doc_scores.sort(key=lambda x: x[1], reverse=True)
        
        return doc_scores[:top_k]
    
    def rerank_to_documents(
        self,
        query: str,
        documents: List[Document],
        top_k: int = 10,
        score_threshold: Optional[float] = None
    ) -> List[Document]:
        """
        Rerank and return only documents (without scores).
        
        Args:
            query: The search query
            documents: List of documents to rerank
            top_k: Number of top documents to return
            score_threshold: Minimum score threshold (optional)
            
        Returns:
            List of documents sorted by relevance
        """
        ranked = self.rerank(query, documents, top_k, score_threshold)
        
        # Add rerank score to metadata and return documents
        result = []
        for doc, score in ranked:
            doc.metadata["rerank_score"] = float(score)
            result.append(doc)
        
        return result


# Global reranker instance
_reranker: Optional[RerankerService] = None


def get_reranker_service() -> RerankerService:
    """Get or create the global reranker service instance."""
    global _reranker
    
    if _reranker is None:
        # Check for Cohere API key
        cohere_key = getattr(config, 'COHERE_API_KEY', None)
        
        _reranker = RerankerService(
            model_name="cross-encoder/ms-marco-MiniLM-L-6-v2",
            use_cohere=bool(cohere_key),
            cohere_api_key=cohere_key
        )
    
    return _reranker

