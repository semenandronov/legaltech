"""
Pydantic схемы для долгосрочной памяти.

Определяют структуру данных для хранения в LangGraph Store.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum


class MemoryNamespace(str, Enum):
    """Пространства имён для разных типов памяти."""
    USER_PROFILE = "user_profile"
    CASE_MEMORY = "case_memory"
    QUERY_HISTORY = "query_history"
    INSIGHTS = "insights"


# ============== User Profile ==============

class LegalPreferences(BaseModel):
    """Юридические предпочтения пользователя."""
    primary_area: Optional[str] = Field(
        None,
        description="Основная область права (гражданское, корпоративное, трудовое и т.д.)"
    )
    secondary_areas: List[str] = Field(
        default_factory=list,
        description="Дополнительные области интересов"
    )
    preferred_sources: List[str] = Field(
        default_factory=list,
        description="Предпочитаемые источники (ГАРАНТ, Консультант+, судебная практика)"
    )
    detail_level: Literal["brief", "standard", "detailed"] = Field(
        "standard",
        description="Предпочитаемый уровень детализации ответов"
    )


class CommunicationStyle(BaseModel):
    """Стиль коммуникации пользователя."""
    formality: Literal["formal", "neutral", "informal"] = Field(
        "neutral",
        description="Уровень формальности"
    )
    language: str = Field(
        "ru",
        description="Предпочитаемый язык"
    )
    use_legal_terms: bool = Field(
        True,
        description="Использовать юридическую терминологию"
    )
    include_citations: bool = Field(
        True,
        description="Включать цитаты из источников"
    )


class UserProfile(BaseModel):
    """
    Профиль пользователя для персонализации.
    
    Хранится в namespace: user_profile/{user_id}
    """
    user_id: str = Field(..., description="ID пользователя")
    
    # Основная информация
    name: Optional[str] = Field(None, description="Имя пользователя")
    role: Optional[str] = Field(None, description="Роль (юрист, бухгалтер, руководитель)")
    organization: Optional[str] = Field(None, description="Организация")
    
    # Предпочтения
    legal_preferences: LegalPreferences = Field(
        default_factory=LegalPreferences,
        description="Юридические предпочтения"
    )
    communication_style: CommunicationStyle = Field(
        default_factory=CommunicationStyle,
        description="Стиль коммуникации"
    )
    
    # Контекст
    recent_topics: List[str] = Field(
        default_factory=list,
        description="Недавние темы обсуждения"
    )
    expertise_level: Literal["beginner", "intermediate", "expert"] = Field(
        "intermediate",
        description="Уровень юридической экспертизы"
    )
    
    # Метаданные
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# ============== Case Memory ==============

class CaseParticipant(BaseModel):
    """Участник дела."""
    name: str = Field(..., description="Имя участника")
    role: str = Field(..., description="Роль (истец, ответчик, третье лицо)")
    details: Optional[str] = Field(None, description="Дополнительная информация")


class ImportantDate(BaseModel):
    """Важная дата по делу."""
    date: str = Field(..., description="Дата в формате YYYY-MM-DD")
    description: str = Field(..., description="Описание события")
    is_deadline: bool = Field(False, description="Является ли дедлайном")


class KeyFact(BaseModel):
    """Ключевой факт по делу."""
    fact: str = Field(..., description="Описание факта")
    source: Optional[str] = Field(None, description="Источник (документ)")
    importance: Literal["low", "medium", "high", "critical"] = Field(
        "medium",
        description="Важность факта"
    )
    verified: bool = Field(False, description="Подтверждён ли факт")


class CaseMemory(BaseModel):
    """
    Память по конкретному делу.
    
    Хранится в namespace: case_memory/{case_id}
    """
    case_id: str = Field(..., description="ID дела")
    user_id: str = Field(..., description="ID пользователя")
    
    # Основная информация
    case_name: Optional[str] = Field(None, description="Название дела")
    case_type: Optional[str] = Field(None, description="Тип дела (иск, договор, консультация)")
    status: Literal["active", "pending", "closed"] = Field(
        "active",
        description="Статус дела"
    )
    
    # Участники
    participants: List[CaseParticipant] = Field(
        default_factory=list,
        description="Участники дела"
    )
    
    # Важные даты
    important_dates: List[ImportantDate] = Field(
        default_factory=list,
        description="Важные даты"
    )
    
    # Ключевые факты
    key_facts: List[KeyFact] = Field(
        default_factory=list,
        description="Ключевые факты по делу"
    )
    
    # Краткое содержание
    summary: Optional[str] = Field(None, description="Краткое описание дела")
    legal_basis: List[str] = Field(
        default_factory=list,
        description="Правовые основания (статьи, законы)"
    )
    
    # Рекомендации
    recommendations: List[str] = Field(
        default_factory=list,
        description="Рекомендации по делу"
    )
    risks: List[str] = Field(
        default_factory=list,
        description="Выявленные риски"
    )
    
    # Метаданные
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# ============== Query History ==============

class QueryRecord(BaseModel):
    """
    Запись о запросе пользователя.
    
    Хранится в namespace: query_history/{user_id}
    """
    query_id: str = Field(..., description="ID запроса")
    user_id: str = Field(..., description="ID пользователя")
    case_id: Optional[str] = Field(None, description="ID дела (если применимо)")
    
    # Запрос
    question: str = Field(..., description="Текст вопроса")
    mode: str = Field("normal", description="Режим (normal, deep_think, garant)")
    
    # Ответ
    answer_summary: Optional[str] = Field(None, description="Краткое содержание ответа")
    sources_used: List[str] = Field(
        default_factory=list,
        description="Использованные источники"
    )
    
    # Оценка
    was_helpful: Optional[bool] = Field(None, description="Был ли ответ полезен")
    feedback: Optional[str] = Field(None, description="Обратная связь пользователя")
    
    # Метаданные
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    duration_seconds: Optional[float] = Field(None, description="Время ответа")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# ============== Insights ==============

class Insight(BaseModel):
    """
    Инсайт или вывод.
    
    Хранится в namespace: insights/{user_id} или insights/{case_id}
    """
    insight_id: str = Field(..., description="ID инсайта")
    scope: Literal["user", "case", "global"] = Field(
        "user",
        description="Область применения"
    )
    scope_id: str = Field(..., description="ID пользователя или дела")
    
    # Содержание
    title: str = Field(..., description="Заголовок инсайта")
    description: str = Field(..., description="Описание")
    category: str = Field("general", description="Категория (pattern, risk, recommendation)")
    
    # Источник
    derived_from: List[str] = Field(
        default_factory=list,
        description="Источники (query_ids, document_ids)"
    )
    
    # Важность
    confidence: float = Field(0.8, description="Уверенность (0-1)")
    priority: Literal["low", "medium", "high"] = Field(
        "medium",
        description="Приоритет"
    )
    
    # Статус
    is_actionable: bool = Field(False, description="Требует действия")
    is_acknowledged: bool = Field(False, description="Подтверждён пользователем")
    
    # Метаданные
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = Field(None, description="Срок актуальности")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

