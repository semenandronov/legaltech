"""Structured output schema for RAG responses with mandatory citations

This module provides Pydantic schemas for structured RAG responses that
enforce mandatory citations for all factual claims.
"""
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from app.services.langchain_agents.schemas.base_schema import Confidence
import logging

logger = logging.getLogger(__name__)


class RAGCitation(BaseModel):
    """Citation with mandatory quote verification"""
    doc_id: str = Field(..., description="Document ID from metadata")
    doc_name: Optional[str] = Field(None, description="Document name")
    page: Optional[int] = Field(None, description="Page number")
    char_start: Optional[int] = Field(None, description="Character start offset")
    char_end: Optional[int] = Field(None, description="Character end offset")
    quote: str = Field(..., min_length=10, description="Verbatim quote from source (MUST match exactly)")
    
    @field_validator('quote')
    @classmethod
    def quote_not_empty(cls, v):
        if not v or len(v.strip()) < 10:
            raise ValueError("Quote must be at least 10 characters and non-empty")
        return v.strip()


class RAGClaim(BaseModel):
    """Factual claim with mandatory citations"""
    text: str = Field(..., description="The factual claim")
    citations: List[RAGCitation] = Field(
        ..., 
        min_items=1,  # MANDATORY: at least 1 citation per claim
        description="Supporting citations (REQUIRED, min 1)"
    )
    confidence: Confidence = Field(
        default=Confidence.MEDIUM,
        description="Confidence level based on citations"
    )


class LegalRAGResponse(BaseModel):
    """Structured legal RAG response with mandatory citations"""
    answer: str = Field(..., description="Main legal analysis answer (human-readable)")
    claims: List[RAGClaim] = Field(
        ..., 
        min_items=1,  # At least one claim required
        description="Factual claims supporting the answer, each with citations"
    )
    reasoning: Optional[str] = Field(
        None, 
        description="Brief explanation of analysis approach (optional)"
    )
    confidence_overall: Confidence = Field(
        default=Confidence.MEDIUM,
        description="Overall confidence in the answer"
    )
    
    @field_validator('claims')
    @classmethod
    def claims_not_empty(cls, v):
        if not v:
            raise ValueError("Answer must contain at least one claim with citations")
        return v

