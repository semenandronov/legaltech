"""
Graphs module - LangGraph графы для оркестрации страниц.

Каждый граф соответствует странице приложения и определяет:
- Узлы (nodes) для обработки
- Рёбра (edges) для переходов
- Условные переходы (conditional edges)
- Checkpointing для сохранения состояния

Графы в этом модуле:
- ChatGraph: Граф для AssistantChatPage с режимами
- TabularGraph: Граф для TabularReviewPage с Map-Reduce
- WorkflowGraph: Граф для WorkflowsPage с параллельным выполнением
- AnalysisGraph: Граф для фоновых анализов (timeline, key_facts, etc.)
"""

from app.services.langchain_agents.graphs.chat_graph import create_chat_graph, ChatGraphState
from app.services.langchain_agents.graphs.tabular_graph import create_tabular_graph, TabularGraphState
from app.services.langchain_agents.graphs.workflow_graph import create_workflow_graph, WorkflowGraphState

__all__ = [
    "create_chat_graph",
    "ChatGraphState",
    "create_tabular_graph",
    "TabularGraphState",
    "create_workflow_graph",
    "WorkflowGraphState",
]



