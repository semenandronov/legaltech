"""
Chat module - модуль обработки чат-запросов

Содержит:
- ChatOrchestrator: главный оркестратор запросов
- RequestClassifier: классификация запросов (task/question)
- RAGHandler: обработка RAG-запросов
- DraftHandler: создание документов
- EditorHandler: редактирование документов
- ChatHistoryService: управление историей чата
- SSE события и сериализатор
- OpenAPI схемы
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
from app.services.chat.rag_handler import RAGHandler
from app.services.chat.draft_handler import DraftHandler
from app.services.chat.editor_handler import EditorHandler
from app.services.chat.agent_handler import AgentHandler
from app.services.chat.metrics import ChatMetrics, get_metrics, MetricTimer, Timer

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
    # Handlers
    "RAGHandler",
    "DraftHandler",
    "EditorHandler",
    "AgentHandler",
    # Metrics
    "ChatMetrics",
    "get_metrics",
    "MetricTimer",
    "Timer",
]

