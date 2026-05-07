"""
Schemas for legacy import compatibility in RAG service.
"""

from .citation_schema import (
    CitationSource,
    Claim,
    CitationFirstResponse,
    EnhancedCitation,
    AnswerWithCitations,
)
from .rag_response_schema import (
    Confidence,
    RAGCitation,
    RAGClaim,
    LegalRAGResponse,
)

__all__ = [
    "CitationSource",
    "Claim",
    "CitationFirstResponse",
    "EnhancedCitation",
    "AnswerWithCitations",
    "Confidence",
    "RAGCitation",
    "RAGClaim",
    "LegalRAGResponse",
]
