"""Citation-first schemas for structured JSON generation"""
from typing import List, Optional
from pydantic import BaseModel, Field


class CitationSource(BaseModel):
    """Source citation with provenance information"""
    doc_id: str = Field(description="Document ID for deep linking")
    char_start: Optional[int] = Field(None, description="Start character position in document")
    char_end: Optional[int] = Field(None, description="End character position in document")
    score: float = Field(description="Relevance score (0.0-1.0)")
    verified: bool = Field(default=False, description="Whether citation is verified")
    page: Optional[int] = Field(None, description="Page number if available")
    snippet: Optional[str] = Field(None, description="Text snippet from source")


class Claim(BaseModel):
    """A claim with associated citations"""
    text: str = Field(description="The claim text")
    sources: List[CitationSource] = Field(description="List of source citations supporting this claim")


class CitationFirstResponse(BaseModel):
    """Citation-first response structure with claims and sources"""
    answer: str = Field(description="Main answer text")
    claims: List[Claim] = Field(description="List of claims with citations")
    reasoning: Optional[str] = Field(None, description="Optional reasoning for the answer")


