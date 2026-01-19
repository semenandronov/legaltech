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


class EnhancedCitation(BaseModel):
    """
    Цитата с точными координатами для подсветки в документе.
    
    КЛЮЧЕВОЙ ПРИНЦИП (Harvey/Lexis+ style):
    - chunk_id: уникальный ID chunk'а из которого взята информация
    - char_start/char_end: ТОЧНЫЕ координаты в исходном документе
    - При клике открываем документ по этим координатам - без поиска!
    """
    source_id: str = Field(..., description="ID документа (file_id)")
    file_name: str = Field(..., description="Имя файла")
    page: int = Field(1, description="Номер страницы")
    quote: str = Field(..., description="Текст chunk'а (для превью)")
    char_start: int = Field(..., description="Начальная позиция chunk'а в документе (символ)")
    char_end: int = Field(..., description="Конечная позиция chunk'а в документе (символ)")
    context_before: str = Field("", description="Контекст до цитаты (50 символов)")
    context_after: str = Field("", description="Контекст после цитаты (50 символов)")
    chunk_id: Optional[str] = Field(None, description="Уникальный ID chunk'а для точной навигации")


class AnswerWithCitations(BaseModel):
    """Ответ со структурированными цитатами для inline citations"""
    answer: str = Field(..., description="Ответ с маркерами [1], [2], etc.")
    citations: List[EnhancedCitation] = Field(default_factory=list, description="Список цитат с координатами")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Уверенность в ответе")


