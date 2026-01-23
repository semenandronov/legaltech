"""
LangChain Agents - Страничная архитектура v2

Архитектура построена вокруг страниц приложения:

agents/ — Настоящие агенты (ReAct, с tools, циклами, HITL)
  - ChatReActAgent: Агент для страницы чата
  - TabularExtractionAgent: Агент для Tabular Review (Map-Reduce)
  - WorkflowOrchestratorAgent: Агент для Workflows (планирование, параллелизация)

graphs/ — LangGraph графы для страниц
  - ChatGraph: Граф для AssistantChatPage (режимы: normal/deep_think/garant/draft)
  - TabularGraph: Граф для TabularReviewPage (HITL через interrupt)
  - WorkflowGraph: Граф для WorkflowsPage (параллельное выполнение)

nodes/ — Узлы (простые функции без циклов)
  - discrepancy_risk_node: Объединённый узел противоречий + рисков
  - summary_chain: Упрощённый summary как chain

*_graph_service.py — Сервисы для интеграции графов в API
"""

# Агенты
from app.services.langchain_agents.agents import (
    ChatReActAgent,
    TabularExtractionAgent,
    WorkflowOrchestratorAgent,
)

# Графы
from app.services.langchain_agents.graphs import (
    create_chat_graph,
    ChatGraphState,
    create_tabular_graph,
    TabularGraphState,
    create_workflow_graph,
    WorkflowGraphState,
)

# Сервисы интеграции
from app.services.langchain_agents.chat_graph_service import (
    ChatGraphService,
    get_chat_graph_service,
)
from app.services.langchain_agents.tabular_graph_service import (
    TabularGraphService,
    get_tabular_graph_service,
)
from app.services.langchain_agents.workflow_graph_service import (
    WorkflowGraphService,
    get_workflow_graph_service,
)

# Узлы
from app.services.langchain_agents.nodes import (
    discrepancy_risk_node,
    create_summary_chain,
    summary_chain_node,
)

__all__ = [
    # Агенты
    "ChatReActAgent",
    "TabularExtractionAgent",
    "WorkflowOrchestratorAgent",
    
    # Графы
    "create_chat_graph",
    "ChatGraphState",
    "create_tabular_graph",
    "TabularGraphState",
    "create_workflow_graph",
    "WorkflowGraphState",
    
    # Сервисы
    "ChatGraphService",
    "get_chat_graph_service",
    "TabularGraphService",
    "get_tabular_graph_service",
    "WorkflowGraphService",
    "get_workflow_graph_service",
    
    # Узлы
    "discrepancy_risk_node",
    "create_summary_chain",
    "summary_chain_node",
]
