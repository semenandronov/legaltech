"""
Graphs module - LangGraph графы для оркестрации страниц.

Каждый граф соответствует странице приложения и определяет:
- Узлы (nodes) для обработки
- Рёбра (edges) для переходов
- Условные переходы (conditional edges)
- Checkpointing для сохранения состояния

Графы в этом модуле:
- ChatGraph: Граф для AssistantChatPage с режимами
- AnalysisGraph: Граф для фоновых анализов (timeline, key_facts, etc.)
"""

from app.services.langchain_agents.graphs.chat_graph import create_chat_graph, ChatGraphState

__all__ = [
    "create_chat_graph",
    "ChatGraphState",
]
