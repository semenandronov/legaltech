"""Pydantic схемы для входов tools - типобезопасность и валидация"""
from pydantic import BaseModel, Field
from typing import Optional, List


class DocumentSearchInput(BaseModel):
    """Схема входа для поиска документов"""
    
    query: str = Field(..., description="Поисковый запрос", min_length=1)
    case_id: str = Field(..., description="Идентификатор дела")
    k: int = Field(default=20, ge=1, le=100, description="Количество документов для извлечения (1-100)")
    use_iterative: bool = Field(default=False, description="Использовать итеративный поиск с переформулировкой запроса")
    use_hybrid: bool = Field(default=False, description="Использовать гибридный поиск (семантический + ключевые слова)")
    doc_types: Optional[List[str]] = Field(None, description="Фильтр по типам документов (например, ['contract', 'statement_of_claim'])")


class SaveTimelineInput(BaseModel):
    """Схема входа для сохранения результатов timeline"""
    
    timeline_data: str = Field(..., description="JSON строка с событиями временной линии", min_length=1)
    case_id: str = Field(..., description="Идентификатор дела")


class SaveKeyFactsInput(BaseModel):
    """Схема входа для сохранения результатов key_facts"""
    
    key_facts_data: str = Field(..., description="JSON строка с ключевыми фактами", min_length=1)
    case_id: str = Field(..., description="Идентификатор дела")


class SaveDiscrepancyInput(BaseModel):
    """Схема входа для сохранения результатов discrepancy"""
    
    discrepancy_data: str = Field(..., description="JSON строка с найденными противоречиями", min_length=1)
    case_id: str = Field(..., description="Идентификатор дела")


class SaveRiskInput(BaseModel):
    """Схема входа для сохранения результатов risk analysis"""
    
    risk_data: str = Field(..., description="JSON строка с анализом рисков", min_length=1)
    case_id: str = Field(..., description="Идентификатор дела")


class SaveSummaryInput(BaseModel):
    """Схема входа для сохранения результатов summary"""
    
    summary_data: str = Field(..., description="JSON строка с резюме дела", min_length=1)
    case_id: str = Field(..., description="Идентификатор дела")

