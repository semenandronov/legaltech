from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class CitationSource(BaseModel):
    doc_id: str = Field(..., description="Document identifier")
    char_start: Optional[int] = Field(default=None, description="Start char offset")
    char_end: Optional[int] = Field(default=None, description="End char offset")
    score: float = Field(default=0.0, description="Source relevance score")
    verified: bool = Field(default=False, description="Citation verified flag")
    page: Optional[int] = Field(default=None, description="Source page number")
    snippet: Optional[str] = Field(default=None, description="Quoted snippet")


class Claim(BaseModel):
    text: str = Field(..., description="Claim text")
    sources: List[CitationSource] = Field(default_factory=list, description="Supporting sources")


class CitationFirstResponse(BaseModel):
    answer: str = Field(..., description="Final answer text")
    claims: List[Claim] = Field(default_factory=list, description="Claims with citations")
    reasoning: Optional[str] = Field(default=None, description="Optional model reasoning")


class EnhancedCitation(BaseModel):
    source_id: str
    file_name: str
    page: Optional[int] = None
    quote: str
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    context_before: str = ""
    context_after: str = ""
    chunk_id: Optional[str] = None
    bbox: Optional[dict] = None
    bbox_regions: Optional[List[Dict[str, float]]] = None
    page_bbox: Optional[dict] = None


class AnswerWithCitations(BaseModel):
    answer: str
    citations: List[EnhancedCitation] = Field(default_factory=list)
    confidence: float = 0.0
