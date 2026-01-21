"""
Chat module - модуль обработки чат-запросов

v2.0: Адаптивная архитектура с ReActChatAgent

Содержит:
- ChatOrchestrator: главный оркестратор запросов
- ReActChatAgent: адаптивный агент (сам выбирает инструменты) - НОВОЕ!
- RequestClassifier: классификация запросов (для метрик)
- DraftHandler: создание документов
- EditorHandler: редактирование документов
- ChatHistoryService: управление историей чата
- chat_tools: инструменты для ReActChatAgent - НОВОЕ!
- SSE события и сериализатор
- Метрики
"""

from app.services.chat.events import (
    SSEEvent,
    TextDeltaEvent,
    CitationsEvent,
    ReasoningEvent,
    DocumentCreatedEvent,
    StructuredEditsEvent,
    ErrorEvent,
    PlanApprovalEvent,
    HumanFeedbackEvent,
    AgentProgressEvent,
    SSESerializer,
)
from app.services.chat.classifier import RequestClassifier, ClassificationResult
from app.services.chat.history_service import ChatHistoryService
from app.services.chat.orchestrator import ChatOrchestrator, ChatRequest, get_chat_orchestrator
from app.services.chat.react_chat_agent import ReActChatAgent
from app.services.chat.chat_tools import get_chat_tools
from app.services.chat.draft_handler import DraftHandler
from app.services.chat.editor_handler import EditorHandler
from app.services.chat.metrics import ChatMetrics, get_metrics, MetricTimer, Timer

# Legacy imports (для обратной совместимости)
from app.services.chat.rag_handler import RAGHandler
from app.services.chat.agent_handler import AgentHandler

__all__ = [
    # Events
    "SSEEvent",
    "TextDeltaEvent",
    "CitationsEvent",
    "ReasoningEvent",
    "DocumentCreatedEvent",
    "StructuredEditsEvent",
    "ErrorEvent",
    "PlanApprovalEvent",
    "HumanFeedbackEvent",
    "AgentProgressEvent",
    "SSESerializer",
    # Services
    "RequestClassifier",
    "ClassificationResult",
    "ChatHistoryService",
    # Orchestrator
    "ChatOrchestrator",
    "ChatRequest",
    "get_chat_orchestrator",
    # ReAct Agent (NEW)
    "ReActChatAgent",
    "get_chat_tools",
    # Handlers
    "DraftHandler",
    "EditorHandler",
    # Legacy (for backwards compatibility)
    "RAGHandler",
    "AgentHandler",
    # Metrics
    "ChatMetrics",
    "get_metrics",
    "MetricTimer",
    "Timer",
]

