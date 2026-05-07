from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RAGCitation(BaseModel):
    doc_id: str = Field(..., description="Document identifier")
    quote: str = Field(..., description="Exact quote from source")
    doc_name: Optional[str] = Field(default=None, description="Human readable document name")


class RAGClaim(BaseModel):
    text: str = Field(..., description="Claim text")
    citations: List[RAGCitation] = Field(default_factory=list, description="Claim citations")
    confidence: Confidence = Field(default=Confidence.MEDIUM, description="Claim confidence")


class LegalRAGResponse(BaseModel):
    answer: str = Field(..., description="Final answer text")
    claims: List[RAGClaim] = Field(default_factory=list, description="Structured claims")
    confidence_overall: Confidence = Field(default=Confidence.MEDIUM, description="Overall confidence")
    reasoning: Optional[str] = Field(default=None, description="Optional reasoning")
