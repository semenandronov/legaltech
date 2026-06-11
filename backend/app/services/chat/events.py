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
    citation_id: Optional[str] = Field(
        None,
        description="Стабильный идентификатор цитаты (ключ для UI; не зависит от позиции в массиве)",
    )
    source_id: str = Field(..., description="ID источника")
    file_name: str = Field(..., description="Имя файла")
    page: Optional[int] = Field(None, description="Номер страницы")
    quote: Optional[str] = Field(None, description="Текст цитаты")
    quote_anchor: Optional[str] = Field(
        None,
        description="Якорь для поиска в original_text (срез по char_start:char_end или fallback)",
    )
    text_preview: Optional[str] = Field(
        None,
        description="Полный текст чанка (page_content) для подсветки в PDF, как на странице chunk-lab",
    )
    chunk_id: Optional[str] = Field(None, description="Идентификатор чанка (дедуп/диагностика)")
    char_start: Optional[int] = Field(None, description="Начало цитаты в документе")
    char_end: Optional[int] = Field(None, description="Конец цитаты в документе")
    context_before: Optional[str] = Field(None, description="Контекст до цитаты")
    context_after: Optional[str] = Field(None, description="Контекст после цитаты")
    url: Optional[str] = Field(None, description="URL источника (для справочных правовых источников)")
    source_type: Literal["document", "legal_reference", "web", "external", "legal_corpus"] = Field("document", description="Тип источника")
    doc_type: Optional[str] = Field(None, description="Тип документа")
    doc_date: Optional[str] = Field(None, description="Дата документа")
    doc_number: Optional[str] = Field(None, description="Номер документа")
    bbox: Optional[Dict[str, float]] = Field(None, description="Bounding box coordinates: {x0, y0, x1, y1}")
    bbox_regions: Optional[List[Dict[str, float]]] = Field(
        None,
        description="All Docling prov bboxes for the chunk (PDF user space), for multi-region highlights",
    )
    page_bbox: Optional[Dict[str, float]] = Field(None, description="Page dimensions: {width, height}")
    index: Optional[int] = Field(
        None,
        description="Порядковый номер цитаты в ответе (1..n), см. citations_merge_reducer",
    )
    debug_docling_prov_page_nos: Optional[List[int]] = Field(
        None,
        description="Только dev: сырые prov.page_no из Docling для диагностики нумерации страниц",
    )


class DocumentInfo(BaseModel):
    """Информация о созданном документе"""
    id: str = Field(..., description="ID документа")
    title: str = Field(..., description="Название документа")
    content: Optional[str] = Field(None, description="Превью содержимого")
    case_id: str = Field(..., description="ID дела")


class SelectionRange(BaseModel):
    """ProseMirror selection range for deterministic apply."""
    from_pos: int = Field(..., alias="from", description="Start position")
    to_pos: int = Field(..., alias="to", description="End position")

    model_config = {"populate_by_name": True}


class StructuredEdit(BaseModel):
    """Структурированное изменение документа"""
    id: str = Field(..., description="ID изменения")
    new_text: str = Field(..., description="Новый текст")
    original_text: Optional[str] = Field(None, description="Исходный текст (fallback)")
    node_id: Optional[str] = Field(None, description="TipTap block id (data-id)")
    selection_range: Optional[SelectionRange] = Field(None, description="Exact selection range from editor")
    context_before: Optional[str] = Field(None, description="Контекст до")
    context_after: Optional[str] = Field(None, description="Контекст после")
    found_in_document: bool = Field(True, description="Найден ли текст в документе")
    replace_all: bool = Field(False, description="Replace all occurrences of original_text")


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

class TurnStartedEvent(BaseModel):
    """Начало хода редактора (один user message = один turn)."""
    type: Literal["turn_started"] = "turn_started"
    turn_id: str = Field(..., description="UUID хода")
    intent: Literal["ask", "edit", "draft"] = Field(..., description="Режим UI")
    document_id: Optional[str] = Field(None, description="ID документа редактора")
    status: Literal["running"] = "running"

    def to_sse(self) -> str:
        payload = self.model_dump(exclude_none=True)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class TurnCompletedEvent(BaseModel):
    """Завершение хода — канонический снимок для UI/истории."""
    type: Literal["turn_completed"] = "turn_completed"
    turn_id: str = Field(..., description="UUID хода")
    intent: Literal["ask", "edit", "draft"] = Field(..., description="Режим UI")
    artifact_type: Literal["answer", "patch_set", "draft"] = Field(
        ..., description="Главный артефакт хода"
    )
    status: Literal["success", "error"] = "success"
    answer_chars: int = 0
    citations_count: int = 0
    structured_edits_count: int = 0
    document_id: Optional[str] = None

    def to_sse(self) -> str:
        payload = self.model_dump(exclude_none=True)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class ContentSyncEvent(BaseModel):
    """Полная замена текста ответа (после sanitize), не append."""
    type: Literal["content_sync"] = "content_sync"
    content: str = Field(..., description="Канонический текст ответа")
    turn_id: Optional[str] = None
    intent: Optional[Literal["ask", "edit", "draft"]] = None

    def to_sse(self) -> str:
        payload = self.model_dump(exclude_none=True)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class TextDeltaEvent(BaseModel):
    """Событие дельты текста (streaming ответа)"""
    type: Literal["text_delta"] = "text_delta"
    text_delta: str = Field(..., description="Часть текста ответа")
    
    def to_sse(self) -> str:
        """Сериализация в SSE формат (совместимый с assistant-ui)"""
        return (
            "data: "
            f"{json.dumps({'type': 'text_delta', 'text_delta': self.text_delta, 'textDelta': self.text_delta}, ensure_ascii=False)}"
            "\n\n"
        )


class CitationsEvent(BaseModel):
    """Событие с цитатами/источниками"""
    type: Literal["citations"] = "citations"
    citations: List[Citation] = Field(..., description="Список цитат")
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'citations', 'citations': [c.model_dump() for c in self.citations]}, ensure_ascii=False)}\n\n"


class TabularChatDoneEvent(BaseModel):
    """Финальное событие стрима чата по табличному обзору."""
    type: Literal["tabular_chat_done"] = "tabular_chat_done"
    answer: str = Field(..., description="Полный текст ответа")
    citations: List[Dict[str, str]] = Field(default_factory=list)
    table_stats: Dict[str, int] = Field(default_factory=dict)

    def to_sse(self) -> str:
        return f"data: {json.dumps(self.model_dump(), ensure_ascii=False)}\n\n"


class AnswerBlock(BaseModel):
    """Фрагмент ответа с привязкой к citation_id (Phase 2)."""

    block_id: str = Field(..., description="Идентификатор блока")
    markdown_text: str = Field(..., description="Markdown блока без [N] маркеров")
    citation_ids: List[str] = Field(default_factory=list, description="Стабильные citation_id из каталога")


class AnswerBlocksEvent(BaseModel):
    """Структурированные блоки ответа для UI (NotebookLM-style)."""

    type: Literal["answer_blocks"] = "answer_blocks"
    blocks: List[AnswerBlock] = Field(..., description="Блоки ответа")

    def to_sse(self) -> str:
        payload = {
            "type": "answer_blocks",
            "blocks": [b.model_dump() for b in self.blocks],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class AssistantActivityEvent(BaseModel):
    """Пошаговый прогресс ассистента: стабильный этап + динамические детали из фактов."""
    type: Literal["assistant_activity"] = "assistant_activity"
    step_id: str = Field(..., description="Стабильный id шага для upsert в UI")
    phase: str = Field(..., description="Ключ фазы")
    step: int = Field(..., description="Номер шага")
    total_steps: int = Field(..., alias="totalSteps", description="Всего шагов")
    label: str = Field(..., description="Короткая подпись этапа")
    detail: Optional[str] = Field(None, description="Динамические детали")
    content: str = Field(..., description="Полный текст для UI")
    status: Literal["pending", "running", "completed", "error"] = Field(
        "running",
        description="Статус шага",
    )

    model_config = {"populate_by_name": True}

    def to_sse(self) -> str:
        return (
            f"data: {json.dumps(self.model_dump(by_alias=True), ensure_ascii=False)}\n\n"
        )


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
    
    NEW v3.0: Показывает какие цитаты подтверждены в справочном правовом источнике
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
    TurnStartedEvent,
    TurnCompletedEvent,
    ContentSyncEvent,
    TextDeltaEvent,
    CitationsEvent,
    AnswerBlocksEvent,
    ReasoningEvent,
    AssistantActivityEvent,
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
    def turn_started(
        turn_id: str,
        intent: str,
        *,
        document_id: Optional[str] = None,
    ) -> str:
        return TurnStartedEvent(
            turn_id=turn_id,
            intent=intent,  # type: ignore[arg-type]
            document_id=document_id,
        ).to_sse()

    @staticmethod
    def turn_completed(
        turn_id: str,
        intent: str,
        artifact_type: str,
        *,
        document_id: Optional[str] = None,
        status: str = "success",
        answer_chars: int = 0,
        citations_count: int = 0,
        structured_edits_count: int = 0,
    ) -> str:
        return TurnCompletedEvent(
            turn_id=turn_id,
            intent=intent,  # type: ignore[arg-type]
            artifact_type=artifact_type,  # type: ignore[arg-type]
            document_id=document_id,
            status=status,  # type: ignore[arg-type]
            answer_chars=answer_chars,
            citations_count=citations_count,
            structured_edits_count=structured_edits_count,
        ).to_sse()

    @staticmethod
    def content_sync(content: str, *, turn_id: Optional[str] = None, intent: Optional[str] = None) -> str:
        return ContentSyncEvent(content=content, turn_id=turn_id, intent=intent).to_sse()

    @staticmethod
    def text_delta(text: str) -> str:
        """Быстрый метод для text delta"""
        return TextDeltaEvent(text_delta=text).to_sse()

    @staticmethod
    def tabular_chat_done(
        answer: str,
        citations: List[Dict[str, str]],
        table_stats: Dict[str, int],
    ) -> str:
        return TabularChatDoneEvent(
            answer=answer,
            citations=citations,
            table_stats=table_stats,
        ).to_sse()
    
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
    def assistant_activity(
        *,
        step_id: str,
        phase: str,
        step: int,
        total_steps: int,
        label: str,
        content: str,
        detail: Optional[str] = None,
        status: str = "running",
    ) -> str:
        """Прогресс ассистента: этап + динамические детали."""
        return AssistantActivityEvent(
            step_id=step_id,
            phase=phase,
            step=step,
            total_steps=total_steps,
            label=label,
            detail=detail,
            content=content,
            status=status,  # type: ignore[arg-type]
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
    def answer_blocks(blocks: List[Dict[str, Any]]) -> str:
        """Phase 2: блоки ответа с citation_ids."""
        objs: List[AnswerBlock] = []
        for b in blocks or []:
            if not isinstance(b, dict):
                continue
            try:
                objs.append(
                    AnswerBlock(
                        block_id=str(b.get("block_id") or ""),
                        markdown_text=str(b.get("markdown_text") or ""),
                        citation_ids=[str(x) for x in (b.get("citation_ids") or []) if x is not None],
                    )
                )
            except Exception:
                continue
        if not objs:
            return ""
        return AnswerBlocksEvent(blocks=objs).to_sse()
    
    @staticmethod
    def document_created(doc_id: str, title: str, case_id: str, content: Optional[str] = None) -> str:
        """Быстрый метод для document_created"""
        return DocumentCreatedEvent(
            document=DocumentInfo(id=doc_id, title=title, case_id=case_id, content=content)
        ).to_sse()
    
    @staticmethod
    def structured_edits(edits: List[Dict[str, Any]]) -> str:
        """Быстрый метод для structured_edits из dict"""
        import uuid as _uuid
        edit_objects = []
        for e in edits:
            if not isinstance(e, dict):
                continue
            payload = dict(e)
            if not payload.get("id"):
                payload["id"] = f"edit-{_uuid.uuid4().hex[:8]}"
            if payload.get("new_text") is None:
                payload["new_text"] = ""
            edit_objects.append(StructuredEdit(**payload))
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

    @staticmethod
    def session(session_id: str) -> str:
        """Единое событие с идентификатором сессии."""
        return f"data: {json.dumps({'type': 'session', 'session_id': session_id}, ensure_ascii=False)}\n\n"

    @staticmethod
    def trace(trace_id: str) -> str:
        """Единое событие с trace идентификатором."""
        return f"data: {json.dumps({'type': 'trace', 'trace_id': trace_id}, ensure_ascii=False)}\n\n"

    @staticmethod
    def status(phase: str, **payload: Any) -> str:
        """Единое событие статуса выполнения."""
        data: Dict[str, Any] = {"type": "status", "phase": phase}
        data.update(payload)
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    @staticmethod
    def finish(
        finish_reason: str = "stop",
        *,
        draft_state: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> str:
        """Единое событие завершения потока."""
        data: Dict[str, Any] = {"type": "finish", "finishReason": finish_reason}
        if draft_state:
            data["draft_state"] = draft_state
        if mode:
            data["mode"] = mode
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


