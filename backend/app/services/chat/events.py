"""
SSE Events - Типизированные события для Server-Sent Events

Унифицированная система типов для всех SSE событий чата.
Обеспечивает типобезопасность и консистентность между backend и frontend.
"""
from typing import Union, Literal, List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import json


# =============================================================================
# Вспомогательные модели
# =============================================================================

class Citation(BaseModel):
    """Цитата из документа"""
    source_id: str = Field(..., description="ID источника")
    file_name: str = Field(..., description="Имя файла")
    page: Optional[int] = Field(None, description="Номер страницы")
    quote: Optional[str] = Field(None, description="Текст цитаты")
    char_start: Optional[int] = Field(None, description="Начало цитаты в документе")
    char_end: Optional[int] = Field(None, description="Конец цитаты в документе")
    context_before: Optional[str] = Field(None, description="Контекст до цитаты")
    context_after: Optional[str] = Field(None, description="Контекст после цитаты")
    url: Optional[str] = Field(None, description="URL источника (для ГАРАНТ)")
    source_type: Literal["document", "garant", "web"] = Field("document", description="Тип источника")
    doc_type: Optional[str] = Field(None, description="Тип документа")
    doc_date: Optional[str] = Field(None, description="Дата документа")
    doc_number: Optional[str] = Field(None, description="Номер документа")


class DocumentInfo(BaseModel):
    """Информация о созданном документе"""
    id: str = Field(..., description="ID документа")
    title: str = Field(..., description="Название документа")
    content: Optional[str] = Field(None, description="Превью содержимого")
    case_id: str = Field(..., description="ID дела")


class StructuredEdit(BaseModel):
    """Структурированное изменение документа"""
    id: str = Field(..., description="ID изменения")
    original_text: str = Field(..., description="Исходный текст")
    new_text: str = Field(..., description="Новый текст")
    context_before: Optional[str] = Field(None, description="Контекст до")
    context_after: Optional[str] = Field(None, description="Контекст после")
    found_in_document: bool = Field(True, description="Найден ли текст в документе")


class PlanStep(BaseModel):
    """Шаг плана анализа"""
    description: str = Field(..., description="Описание шага")
    agent_name: Optional[str] = Field(None, description="Имя агента")
    estimated_time: Optional[str] = Field(None, description="Оценка времени")


class PlanInfo(BaseModel):
    """Информация о плане анализа"""
    plan_id: str = Field(..., description="ID плана")
    reasoning: Optional[str] = Field(None, description="Обоснование плана")
    analysis_types: Optional[List[str]] = Field(None, description="Типы анализов")
    confidence: Optional[float] = Field(None, description="Уверенность")
    goals: Optional[List[Dict[str, str]]] = Field(None, description="Цели")
    steps: Optional[List[PlanStep]] = Field(None, description="Шаги")
    strategy: Optional[str] = Field(None, description="Стратегия")


class FeedbackOption(BaseModel):
    """Опция для human feedback"""
    id: str = Field(..., description="ID опции")
    label: str = Field(..., description="Текст опции")


# =============================================================================
# SSE События
# =============================================================================

class TextDeltaEvent(BaseModel):
    """Событие дельты текста (streaming ответа)"""
    type: Literal["text_delta"] = "text_delta"
    text_delta: str = Field(..., description="Часть текста ответа")
    
    def to_sse(self) -> str:
        """Сериализация в SSE формат (совместимый с assistant-ui)"""
        return f"data: {json.dumps({'textDelta': self.text_delta}, ensure_ascii=False)}\n\n"


class CitationsEvent(BaseModel):
    """Событие с цитатами/источниками"""
    type: Literal["citations"] = "citations"
    citations: List[Citation] = Field(..., description="Список цитат")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'citations', 'citations': [c.model_dump() for c in self.citations]}, ensure_ascii=False)}\n\n"


class ReasoningEvent(BaseModel):
    """Событие шага мышления (thinking)"""
    type: Literal["reasoning"] = "reasoning"
    phase: str = Field(..., description="Фаза мышления")
    step: int = Field(..., description="Номер шага")
    total_steps: int = Field(..., description="Всего шагов")
    content: str = Field(..., description="Содержание шага")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'reasoning', 'phase': self.phase, 'step': self.step, 'totalSteps': self.total_steps, 'content': self.content}, ensure_ascii=False)}\n\n"


class DocumentCreatedEvent(BaseModel):
    """Событие создания документа (draft mode)"""
    type: Literal["document_created"] = "document_created"
    document: DocumentInfo = Field(..., description="Информация о документе")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'document_created', 'document': self.document.model_dump()}, ensure_ascii=False)}\n\n"


class StructuredEditsEvent(BaseModel):
    """Событие структурированных изменений (editor mode)"""
    type: Literal["structured_edits"] = "structured_edits"
    edits: List[StructuredEdit] = Field(..., description="Список изменений")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'structured_edits': [e.model_dump() for e in self.edits]}, ensure_ascii=False)}\n\n"


class EditedContentEvent(BaseModel):
    """Событие отредактированного контента (legacy)"""
    type: Literal["edited_content"] = "edited_content"
    edited_content: str = Field(..., description="Отредактированный HTML")
    structured_edits: Optional[List[StructuredEdit]] = Field(None, description="Структурированные изменения")
    
    def to_sse(self) -> str:
        data = {'type': 'edited_content', 'edited_content': self.edited_content}
        if self.structured_edits:
            data['structured_edits'] = [e.model_dump() for e in self.structured_edits]
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


class ErrorEvent(BaseModel):
    """Событие ошибки"""
    type: Literal["error"] = "error"
    error: str = Field(..., description="Текст ошибки")
    error_type: Optional[str] = Field(None, description="Тип ошибки")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'error': self.error}, ensure_ascii=False)}\n\n"


class PlanApprovalEvent(BaseModel):
    """Событие запроса одобрения плана"""
    type: Literal["plan_approval"] = "plan_approval"
    plan: PlanInfo = Field(..., description="План для одобрения")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'plan_approval', 'plan': self.plan.model_dump()}, ensure_ascii=False)}\n\n"


class HumanFeedbackEvent(BaseModel):
    """Событие запроса обратной связи от пользователя"""
    type: Literal["human_feedback_request"] = "human_feedback_request"
    request_id: str = Field(..., description="ID запроса")
    message: str = Field(..., description="Сообщение для пользователя")
    options: Optional[List[FeedbackOption]] = Field(None, description="Варианты ответа")
    agent_name: Optional[str] = Field(None, description="Имя агента")
    
    def to_sse(self) -> str:
        data = {
            'type': 'human_feedback_request',
            'request_id': self.request_id,
            'message': self.message
        }
        if self.options:
            data['options'] = [o.model_dump() for o in self.options]
        if self.agent_name:
            data['agent_name'] = self.agent_name
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


class AgentProgressEvent(BaseModel):
    """Событие прогресса агента"""
    type: Literal["agent_progress"] = "agent_progress"
    agent_name: str = Field(..., description="Имя агента")
    step: str = Field(..., description="Текущий шаг")
    progress: float = Field(..., ge=0.0, le=1.0, description="Прогресс (0-1)")
    message: Optional[str] = Field(None, description="Сообщение")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'agent_progress', 'agent': self.agent_name, 'step': self.step, 'progress': self.progress, 'message': self.message}, ensure_ascii=False)}\n\n"


class AgentCompleteEvent(BaseModel):
    """Событие завершения работы агента"""
    type: Literal["agent_complete"] = "agent_complete"
    agent_name: str = Field(..., description="Имя агента")
    result: Dict[str, Any] = Field(..., description="Результат")
    success: bool = Field(True, description="Успешность")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'agent_complete', 'agent': self.agent_name, 'success': self.success, 'result': self.result}, ensure_ascii=False)}\n\n"


class TableCreatedEvent(BaseModel):
    """Событие создания таблицы"""
    type: Literal["table_created"] = "table_created"
    table_id: str = Field(..., description="ID таблицы")
    table_name: str = Field(..., description="Название таблицы")
    case_id: str = Field(..., description="ID дела")
    preview: Optional[List[Dict[str, Any]]] = Field(None, description="Превью данных")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'table_created', 'table_id': self.table_id, 'table_name': self.table_name, 'case_id': self.case_id, 'preview': self.preview}, ensure_ascii=False)}\n\n"


class AgentStepEvent(BaseModel):
    """
    Событие шага агента (для Reflection, Citation Verification и т.д.)
    
    NEW v3.0: Используется для передачи метаданных о проверках
    """
    type: Literal["agent_step"] = "agent_step"
    step_type: str = Field(..., description="Тип шага: reflection_result, citation_verification, confidence_score")
    content: str = Field(..., description="JSON-контент шага")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'agent_step', 'step_type': self.step_type, 'content': self.content}, ensure_ascii=False)}\n\n"


class ConfidenceScoreEvent(BaseModel):
    """
    Событие с оценкой уверенности в ответе
    
    NEW v3.0: Показывает насколько агент уверен в своём ответе
    """
    type: Literal["confidence_score"] = "confidence_score"
    score: float = Field(..., ge=0.0, le=1.0, description="Оценка уверенности (0-1)")
    level: Literal["very_low", "low", "medium", "high"] = Field(..., description="Уровень уверенности")
    details: Optional[Dict[str, Any]] = Field(None, description="Детали оценки")
    
    def to_sse(self) -> str:
        data = {
            'type': 'confidence_score',
            'score': self.score,
            'level': self.level
        }
        if self.details:
            data['details'] = self.details
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


class CitationVerificationEvent(BaseModel):
    """
    Событие с результатами проверки цитат
    
    NEW v3.0: Показывает какие цитаты подтверждены в ГАРАНТ
    """
    type: Literal["citation_verification"] = "citation_verification"
    total_citations: int = Field(..., description="Всего цитат")
    verified_count: int = Field(..., description="Подтверждённых")
    not_found_count: int = Field(..., description="Не найденных")
    overall_confidence: float = Field(..., ge=0.0, le=1.0, description="Общая уверенность в цитатах")
    citations: Optional[List[Dict[str, Any]]] = Field(None, description="Список цитат с результатами")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'citation_verification', 'total_citations': self.total_citations, 'verified_count': self.verified_count, 'not_found_count': self.not_found_count, 'overall_confidence': self.overall_confidence, 'citations': self.citations}, ensure_ascii=False)}\n\n"


class ReflectionResultEvent(BaseModel):
    """
    Событие с результатами рефлексии (самопроверки)
    
    NEW v3.0: Показывает результат самопроверки ответа
    """
    type: Literal["reflection_result"] = "reflection_result"
    is_valid: bool = Field(..., description="Ответ валиден?")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Оценка уверенности")
    confidence_level: Literal["very_low", "low", "medium", "high"] = Field(..., description="Уровень уверенности")
    issues_count: int = Field(0, description="Количество проблем")
    has_improvement: bool = Field(False, description="Есть улучшенный ответ?")
    critique: Optional[str] = Field(None, description="Критика ответа")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'reflection_result', 'is_valid': self.is_valid, 'confidence_score': self.confidence_score, 'confidence_level': self.confidence_level, 'issues_count': self.issues_count, 'has_improvement': self.has_improvement, 'critique': self.critique}, ensure_ascii=False)}\n\n"


class ToolCallEvent(BaseModel):
    """Событие вызова инструмента с отслеживанием статуса"""
    type: Literal["tool_call"] = "tool_call"
    name: str = Field(..., description="Название инструмента")
    status: Literal["running", "completed", "error"] = Field(..., description="Статус выполнения")
    input: Optional[str] = Field(None, description="Входные параметры (JSON)")
    output: Optional[str] = Field(None, description="Результат выполнения (превью)")

    def to_sse(self) -> str:
        data: Dict[str, Any] = {'type': 'tool_call', 'name': self.name, 'status': self.status}
        if self.input:
            data['input'] = self.input
        if self.output:
            data['output'] = self.output
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


class PlaybookCheckResultEvent(BaseModel):
    """Событие с результатами проверки Playbook — показывает детальный отчёт в чате"""
    type: Literal["playbook_check_result"] = "playbook_check_result"
    check: Dict[str, Any] = Field(..., description="Структурированный результат проверки")

    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'playbook_check_result', 'check': self.check}, ensure_ascii=False)}\n\n"


# =============================================================================
# Union Type для всех событий
# =============================================================================

SSEEvent = Union[
    TextDeltaEvent,
    CitationsEvent,
    ReasoningEvent,
    DocumentCreatedEvent,
    StructuredEditsEvent,
    EditedContentEvent,
    ErrorEvent,
    PlanApprovalEvent,
    HumanFeedbackEvent,
    AgentProgressEvent,
    AgentCompleteEvent,
    TableCreatedEvent,
    ToolCallEvent,
    # NEW v3.0: События для Reflection и Citation Verification
    AgentStepEvent,
    ConfidenceScoreEvent,
    CitationVerificationEvent,
    ReflectionResultEvent,
]


# =============================================================================
# SSE Сериализатор
# =============================================================================

class SSESerializer:
    """Унифицированный сериализатор SSE событий"""
    
    @staticmethod
    def serialize(event: SSEEvent) -> str:
        """
        Сериализует событие в SSE формат
        
        Args:
            event: Типизированное SSE событие
            
        Returns:
            Строка в формате SSE (data: {...}\n\n)
        """
        return event.to_sse()
    
    @staticmethod
    def text_delta(text: str) -> str:
        """Быстрый метод для text delta"""
        return TextDeltaEvent(text_delta=text).to_sse()
    
    @staticmethod
    def error(message: str, error_type: Optional[str] = None) -> str:
        """Быстрый метод для ошибки"""
        return ErrorEvent(error=message, error_type=error_type).to_sse()
    
    @staticmethod
    def reasoning(phase: str, step: int, total_steps: int, content: str) -> str:
        """Быстрый метод для reasoning"""
        return ReasoningEvent(
            phase=phase,
            step=step,
            total_steps=total_steps,
            content=content
        ).to_sse()
    
    @staticmethod
    def citations(citations: List[Dict[str, Any]]) -> str:
        """Быстрый метод для citations из dict"""
        citation_objects = []
        for c in citations:
            try:
                # Only pass fields that Citation model accepts
                valid_fields = {k: v for k, v in c.items() if k in Citation.model_fields}
                citation_objects.append(Citation(**valid_fields))
            except Exception:
                # Skip malformed citations rather than failing entirely
                continue
        return CitationsEvent(citations=citation_objects).to_sse()
    
    @staticmethod
    def document_created(doc_id: str, title: str, case_id: str, content: Optional[str] = None) -> str:
        """Быстрый метод для document_created"""
        return DocumentCreatedEvent(
            document=DocumentInfo(id=doc_id, title=title, case_id=case_id, content=content)
        ).to_sse()
    
    @staticmethod
    def structured_edits(edits: List[Dict[str, Any]]) -> str:
        """Быстрый метод для structured_edits из dict"""
        edit_objects = [StructuredEdit(**e) for e in edits]
        return StructuredEditsEvent(edits=edit_objects).to_sse()
    
    @staticmethod
    def tool_call(name: str, status: str, input: Optional[str] = None, output: Optional[str] = None) -> str:
        """Быстрый метод для tool_call"""
        return ToolCallEvent(name=name, status=status, input=input, output=output).to_sse()

    @staticmethod
    def agent_step(step_type: str, content: str) -> str:
        """Быстрый метод для agent_step (Reflection, Citation Verification)"""
        return AgentStepEvent(step_type=step_type, content=content).to_sse()
    
    @staticmethod
    def confidence_score(score: float, level: str, details: Optional[Dict[str, Any]] = None) -> str:
        """Быстрый метод для confidence_score"""
        return ConfidenceScoreEvent(score=score, level=level, details=details).to_sse()
    
    @staticmethod
    def citation_verification(
        total: int,
        verified: int,
        not_found: int,
        confidence: float,
        citations: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Быстрый метод для citation_verification"""
        return CitationVerificationEvent(
            total_citations=total,
            verified_count=verified,
            not_found_count=not_found,
            overall_confidence=confidence,
            citations=citations
        ).to_sse()
    
    @staticmethod
    def reflection_result(
        is_valid: bool,
        confidence_score: float,
        confidence_level: str,
        issues_count: int = 0,
        has_improvement: bool = False,
        critique: Optional[str] = None
    ) -> str:
        """Быстрый метод для reflection_result"""
        return ReflectionResultEvent(
            is_valid=is_valid,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            issues_count=issues_count,
            has_improvement=has_improvement,
            critique=critique
        ).to_sse()

    @staticmethod
    def playbook_check_result(check: Dict[str, Any]) -> str:
        """Быстрый метод для playbook_check_result"""
        return PlaybookCheckResultEvent(check=check).to_sse()


