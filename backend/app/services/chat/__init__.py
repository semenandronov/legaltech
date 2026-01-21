"""
Chat module - модуль обработки чат-запросов

v3.0: Автономная архитектура с AutonomousChatAgent

Содержит:
- ChatOrchestrator: главный оркестратор запросов
- AutonomousChatAgent: автономный агент с динамическим планированием - НОВОЕ v3.0!
- ReActChatAgent: адаптивный агент с фиксированными инструментами (legacy)
- RequestClassifier: классификация запросов (для метрик)
- DraftHandler: создание документов
- EditorHandler: редактирование документов
- ChatHistoryService: управление историей чата
- chat_tools: инструменты для ReActChatAgent
- SSE события и сериализатор
- Метрики

Ключевое отличие v3.0:
- AutonomousChatAgent НЕ ограничен фиксированными инструментами
- Сам анализирует задачу и создаёт КАСТОМНЫЙ план
- 4 фазы: UNDERSTANDING → PLANNING → EXECUTION → SYNTHESIS
- Может решить ЛЮБУЮ задачу
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
from app.services.chat.autonomous_agent import AutonomousChatAgent
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
    # Autonomous Agent (NEW v3.0)
    "AutonomousChatAgent",
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

