"""
Chat module - модуль обработки чат-запросов

v6.0: маршрутизация fast/deep/clarify + graph runtime

Содержит:
- ChatOrchestrator: главный оркестратор запросов
- EditorHandler: редактирование документов
- ChatHistoryService: управление историей чата
- SSE события и сериализатор
- Метрики

Ключевые возможности v6.0:
- Deterministic fast path для простых case-вопросов
- Deep path gating через feature flags
- Clarification path без legacy runtime
- Интеграция quality/budget gates
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
from app.services.chat.universal_tools import get_universal_tools
from app.services.chat.editor_handler import EditorHandler
from app.services.chat.metrics import ChatMetrics, get_metrics, MetricTimer, Timer
from app.services.chat.conversation_policy_service import ConversationPolicyService, RunContext
from app.services.chat.legal_quality_gates import LegalQualityGates, GateResult

# Orchestrator импортируется лениво: иначе цикл chat_graph → citation_payload → chat → orchestrator → chat_graph_service → chat_graph.


def __getattr__(name: str):
    if name in ("ChatOrchestrator", "ChatRequest", "get_chat_orchestrator"):
        from app.services.chat.orchestrator import (
            ChatOrchestrator,
            ChatRequest,
            get_chat_orchestrator,
        )
        return {
            "ChatOrchestrator": ChatOrchestrator,
            "ChatRequest": ChatRequest,
            "get_chat_orchestrator": get_chat_orchestrator,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Legacy imports removed: keep module surface minimal and production-only.

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
    # Tools
    "get_universal_tools",
    # Handlers
    "EditorHandler",
    # Metrics
    "ChatMetrics",
    "get_metrics",
    "MetricTimer",
    "Timer",
    "ConversationPolicyService",
    "RunContext",
    "LegalQualityGates",
    "GateResult",
    # Orchestrator API
    "ChatOrchestrator",
    "ChatRequest",
    "get_chat_orchestrator",
]
