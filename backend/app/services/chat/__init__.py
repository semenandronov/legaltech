"""
Chat module - модуль обработки чат-запросов

v4.0: Классический ReAct с 12 универсальными инструментами

Содержит:
- ChatOrchestrator: главный оркестратор запросов
- SimpleReActAgent: классический ReAct агент с 12 инструментами - НОВОЕ v4.0!
- universal_tools: 12 универсальных инструментов для агента
- RequestClassifier: классификация запросов (для метрик)
- DraftHandler: создание документов
- EditorHandler: редактирование документов
- ChatHistoryService: управление историей чата
- SSE события и сериализатор
- Метрики

Ключевое отличие v4.0:
- SimpleReActAgent использует классический ReAct цикл
- 12 универсальных инструментов (документы, законы, генерация, playbook, вспомогательные)
- Агент САМ выбирает какие инструменты использовать
- Think → Act → Observe → Repeat
- НЕ планирует заранее, решает на ходу
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
from app.services.chat.simple_react_agent import SimpleReActAgent
from app.services.chat.universal_tools import get_universal_tools
from app.services.chat.draft_handler import DraftHandler
from app.services.chat.editor_handler import EditorHandler
from app.services.chat.metrics import ChatMetrics, get_metrics, MetricTimer, Timer

# Legacy imports (для обратной совместимости)
from app.services.chat.rag_handler import RAGHandler
from app.services.chat.agent_handler import AgentHandler
from app.services.chat.react_chat_agent import ReActChatAgent
from app.services.chat.chat_tools import get_chat_tools

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
    # ReAct Agent (NEW v4.0)
    "SimpleReActAgent",
    "get_universal_tools",
    # Handlers
    "DraftHandler",
    "EditorHandler",
    # Legacy (for backwards compatibility)
    "RAGHandler",
    "AgentHandler",
    "ReActChatAgent",
    "get_chat_tools",
    # Metrics
    "ChatMetrics",
    "get_metrics",
    "MetricTimer",
    "Timer",
]
