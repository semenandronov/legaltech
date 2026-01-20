"""
Chat Schemas - OpenAPI схемы для чата

Документация формата запросов и ответов API чата.
"""
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from datetime import datetime


# =============================================================================
# Request Schemas
# =============================================================================

class ChatMessageInput(BaseModel):
    """Сообщение в запросе"""
    role: Literal["user", "assistant"] = Field(..., description="Роль: user или assistant")
    content: str = Field(..., description="Содержимое сообщения")
    
    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "Какие ключевые сроки в этом деле?"
            }
        }


class ChatRequest(BaseModel):
    """
    Запрос к API чата
    
    Поддерживает различные режимы работы:
    - Обычный режим: RAG-ответы на вопросы
    - Draft mode: создание документов
    - Editor mode: редактирование документов
    """
    messages: List[ChatMessageInput] = Field(..., description="Массив сообщений")
    case_id: str = Field(..., description="ID дела", alias="caseId")
    
    # Режимы
    web_search: bool = Field(False, description="Включить веб-поиск")
    legal_research: bool = Field(False, description="Включить поиск в ГАРАНТ")
    deep_think: bool = Field(False, description="Включить глубокое мышление (GigaChat Pro)")
    draft_mode: bool = Field(False, description="Режим создания документа")
    
    # Контекст редактора
    document_context: Optional[str] = Field(None, description="Полный текст документа (для редактора)")
    document_id: Optional[str] = Field(None, description="ID документа")
    selected_text: Optional[str] = Field(None, description="Выделенный текст")
    
    # Шаблон для draft mode
    template_file_id: Optional[str] = Field(None, description="ID файла-шаблона из БД")
    template_file_content: Optional[str] = Field(None, description="HTML контент локального шаблона")
    
    # Прикреплённые файлы
    attached_file_ids: Optional[List[str]] = Field(None, description="ID прикреплённых файлов")
    
    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "messages": [
                    {"role": "user", "content": "Какие ключевые сроки в этом деле?"}
                ],
                "case_id": "550e8400-e29b-41d4-a716-446655440000",
                "legal_research": True,
                "deep_think": False
            }
        }


# =============================================================================
# Response Schemas (SSE Events)
# =============================================================================

class TextDeltaResponse(BaseModel):
    """Событие дельты текста (streaming)"""
    textDelta: str = Field(..., description="Часть текста ответа")
    
    class Config:
        json_schema_extra = {
            "example": {"textDelta": "Согласно статье 135 ГПК РФ..."}
        }


class CitationResponse(BaseModel):
    """Цитата из источника"""
    source_id: str = Field(..., description="ID источника")
    file_name: str = Field(..., description="Имя файла")
    page: Optional[int] = Field(None, description="Номер страницы")
    quote: str = Field(..., description="Текст цитаты")
    char_start: Optional[int] = Field(None, description="Начало цитаты в документе")
    char_end: Optional[int] = Field(None, description="Конец цитаты в документе")
    url: Optional[str] = Field(None, description="URL источника (для ГАРАНТ)")
    source_type: Literal["document", "garant", "web"] = Field("document", description="Тип источника")
    
    class Config:
        json_schema_extra = {
            "example": {
                "source_id": "doc-123",
                "file_name": "Договор поставки.pdf",
                "page": 5,
                "quote": "Срок поставки составляет 30 дней…",
                "source_type": "document"
            }
        }


class CitationsResponse(BaseModel):
    """Событие с цитатами"""
    type: Literal["citations"] = "citations"
    citations: List[CitationResponse] = Field(..., description="Список цитат")


class ReasoningResponse(BaseModel):
    """Событие шага мышления (thinking)"""
    type: Literal["reasoning"] = "reasoning"
    phase: str = Field(..., description="Фаза мышления")
    step: int = Field(..., description="Номер шага")
    totalSteps: int = Field(..., description="Всего шагов")
    content: str = Field(..., description="Содержание шага")
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "reasoning",
                "phase": "understanding",
                "step": 1,
                "totalSteps": 5,
                "content": "Анализирую запрос пользователя…"
            }
        }


class DocumentCreatedResponse(BaseModel):
    """Событие создания документа"""
    type: Literal["document_created"] = "document_created"
    document: Dict[str, Any] = Field(..., description="Информация о документе")
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "document_created",
                "document": {
                    "id": "doc-456",
                    "title": "Исковое заявление",
                    "case_id": "case-123"
                }
            }
        }


class StructuredEditResponse(BaseModel):
    """Структурированное изменение"""
    id: str = Field(..., description="ID изменения")
    original_text: str = Field(..., description="Исходный текст")
    new_text: str = Field(..., description="Новый текст")
    context_before: Optional[str] = Field(None, description="Контекст до")
    context_after: Optional[str] = Field(None, description="Контекст после")
    found_in_document: bool = Field(True, description="Найден ли текст в документе")


class StructuredEditsResponse(BaseModel):
    """Событие структурированных изменений"""
    structured_edits: List[StructuredEditResponse] = Field(..., description="Список изменений")


class ErrorResponse(BaseModel):
    """Событие ошибки"""
    error: str = Field(..., description="Текст ошибки")
    
    class Config:
        json_schema_extra = {
            "example": {"error": "Дело не найдено"}
        }


class ChatStreamResponse(BaseModel):
    """
    Документация формата SSE ответа
    
    Ответ приходит в формате Server-Sent Events (SSE).
    Каждое событие имеет формат: `data: {JSON}\n\n`
    
    Типы событий:
    - TextDelta: часть текста ответа
    - Citations: источники/цитаты
    - Reasoning: шаги мышления
    - DocumentCreated: создан документ
    - StructuredEdits: изменения для редактора
    - Error: ошибка
    """
    
    class Config:
        json_schema_extra = {
            "description": "SSE stream с событиями",
            "example": {
                "events": [
                    {"textDelta": "Согласно статье 135 ГПК РФ..."},
                    {"type": "reasoning", "phase": "understanding", "step": 1, "totalSteps": 5, "content": "..."},
                    {"type": "citations", "citations": [{"source_id": "doc-1", "file_name": "file.pdf", "quote": "..."}]}
                ]
            }
        }


# =============================================================================
# History Schemas
# =============================================================================

class ChatMessageResponse(BaseModel):
    """Сообщение в истории"""
    id: str = Field(..., description="ID сообщения")
    role: Literal["user", "assistant"] = Field(..., description="Роль")
    content: str = Field(..., description="Содержимое")
    source_references: Optional[List[Dict[str, Any]]] = Field(None, description="Источники")
    created_at: Optional[datetime] = Field(None, description="Время создания")
    session_id: Optional[str] = Field(None, description="ID сессии")


class ChatHistoryResponse(BaseModel):
    """Ответ с историей чата"""
    messages: List[ChatMessageResponse] = Field(..., description="Список сообщений")


class ChatSessionResponse(BaseModel):
    """Информация о сессии"""
    session_id: str = Field(..., description="ID сессии")
    first_message: str = Field(..., description="Превью первого сообщения")
    last_message: str = Field(..., description="Превью последнего сообщения")
    first_message_at: Optional[str] = Field(None, description="Время первого сообщения")
    last_message_at: Optional[str] = Field(None, description="Время последнего сообщения")
    message_count: int = Field(..., description="Количество сообщений")


class ChatSessionsResponse(BaseModel):
    """Ответ со списком сессий"""
    sessions: List[ChatSessionResponse] = Field(..., description="Список сессий")


