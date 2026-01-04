"""Streaming Events - Pydantic модели для унифицированных streaming событий"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum


class StreamEventType(str, Enum):
    """Типы streaming событий"""
    RAG_RESPONSE = "rag_response"
    AGENT_PROGRESS = "agent_progress"
    AGENT_COMPLETE = "agent_complete"
    ERROR = "error"
    SOURCES = "sources"
    PLAN_READY = "plan_ready"
    HUMAN_FEEDBACK_REQUEST = "human_feedback_request"
    METADATA = "metadata"


class StreamEvent(BaseModel):
    """Базовое событие для streaming"""
    type: str = Field(..., description="Тип события")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Временная метка события")
    data: Dict[str, Any] = Field(default_factory=dict, description="Данные события")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RAGResponseEvent(BaseModel):
    """Событие RAG ответа"""
    type: Literal["rag_response"] = "rag_response"
    text_delta: str = Field(..., description="Дельта текста ответа")
    sources: Optional[List[Dict[str, Any]]] = Field(None, description="Источники информации")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Дополнительные метаданные")
    
    def to_sse_format(self) -> str:
        """Преобразовать в формат SSE для assistant-ui"""
        import json
        return f"data: {json.dumps({'textDelta': self.text_delta}, ensure_ascii=False)}\n\n"


class AgentProgressEvent(BaseModel):
    """Событие прогресса агента"""
    type: Literal["agent_progress"] = "agent_progress"
    agent_name: str = Field(..., description="Имя агента")
    step: str = Field(..., description="Текущий шаг")
    progress: float = Field(..., ge=0.0, le=1.0, description="Прогресс выполнения (0.0-1.0)")
    message: Optional[str] = Field(None, description="Сообщение о прогрессе")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Дополнительные метаданные")
    
    def to_sse_format(self) -> str:
        """Преобразовать в формат SSE"""
        import json
        return f"data: {json.dumps({'type': 'agent_progress', 'agent': self.agent_name, 'step': self.step, 'progress': self.progress, 'message': self.message}, ensure_ascii=False)}\n\n"


class AgentCompleteEvent(BaseModel):
    """Событие завершения работы агента"""
    type: Literal["agent_complete"] = "agent_complete"
    agent_name: str = Field(..., description="Имя агента")
    result: Dict[str, Any] = Field(..., description="Результат работы агента")
    success: bool = Field(True, description="Успешность выполнения")
    error: Optional[str] = Field(None, description="Ошибка если была")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Дополнительные метаданные")
    
    def to_sse_format(self) -> str:
        """Преобразовать в формат SSE"""
        import json
        return f"data: {json.dumps({'type': 'agent_complete', 'agent': self.agent_name, 'success': self.success, 'result': self.result}, ensure_ascii=False)}\n\n"


class ErrorEvent(BaseModel):
    """Событие ошибки"""
    type: Literal["error"] = "error"
    error: str = Field(..., description="Текст ошибки")
    error_type: Optional[str] = Field(None, description="Тип ошибки")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Дополнительные метаданные")
    
    def to_sse_format(self) -> str:
        """Преобразовать в формат SSE"""
        import json
        return f"data: {json.dumps({'error': self.error}, ensure_ascii=False)}\n\n"


class SourcesEvent(BaseModel):
    """Событие с источниками информации"""
    type: Literal["sources"] = "sources"
    sources: List[Dict[str, Any]] = Field(..., description="Список источников")
    
    def to_sse_format(self) -> str:
        """Преобразовать в формат SSE"""
        import json
        return f"data: {json.dumps({'type': 'sources', 'sources': self.sources}, ensure_ascii=False)}\n\n"


class PlanReadyEvent(BaseModel):
    """Событие готовности плана анализа"""
    type: Literal["plan_ready"] = "plan_ready"
    plan_id: str = Field(..., description="Идентификатор плана")
    plan: Dict[str, Any] = Field(..., description="Данные плана")
    analysis_types: List[str] = Field(..., description="Типы анализов")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Уверенность в плане")
    
    def to_sse_format(self) -> str:
        """Преобразовать в формат SSE"""
        import json
        return f"data: {json.dumps({'type': 'plan_ready', 'planId': self.plan_id, 'plan': self.plan}, ensure_ascii=False)}\n\n"


class HumanFeedbackRequestEvent(BaseModel):
    """Событие запроса обратной связи от пользователя"""
    type: Literal["human_feedback_request"] = "human_feedback_request"
    request_id: str = Field(..., description="Идентификатор запроса")
    question: str = Field(..., description="Вопрос для пользователя")
    context: Optional[Dict[str, Any]] = Field(None, description="Контекст запроса")
    options: Optional[List[str]] = Field(None, description="Варианты ответов")
    requires_approval: bool = Field(False, description="Требуется ли одобрение")
    
    def to_sse_format(self) -> str:
        """Преобразовать в формат SSE"""
        import json
        return f"data: {json.dumps({'type': 'human_feedback_request', 'requestId': self.request_id, 'question': self.question, 'options': self.options}, ensure_ascii=False)}\n\n"


class MetadataEvent(BaseModel):
    """Событие с метаданными"""
    type: Literal["metadata"] = "metadata"
    metadata: Dict[str, Any] = Field(..., description="Метаданные")
    
    def to_sse_format(self) -> str:
        """Преобразовать в формат SSE"""
        import json
        return f"data: {json.dumps({'type': 'metadata', 'metadata': self.metadata}, ensure_ascii=False)}\n\n"


# Union type для всех событий
StreamEventUnion = (
    RAGResponseEvent |
    AgentProgressEvent |
    AgentCompleteEvent |
    ErrorEvent |
    SourcesEvent |
    PlanReadyEvent |
    HumanFeedbackRequestEvent |
    MetadataEvent
)

