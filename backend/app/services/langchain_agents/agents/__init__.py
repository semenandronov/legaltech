"""
Agents module - настоящие агенты с принятием решений.

Согласно LangGraph документации, агент отличается от узла (node) тем, что:
1. Принимает решения о следующем действии
2. Может использовать tools в цикле
3. Имеет условную логику на основе результатов

Агенты в этом модуле:
- ChatAgent: ReAct агент для страницы чата с режимами (normal/deep_think/garant/draft)
- TabularAgent: Агент для Tabular Review с Map-Reduce и HITL
- WorkflowAgent: Оркестратор workflows с планированием и одобрением
"""

from app.services.langchain_agents.agents.chat_react_agent import ChatReActAgent
from app.services.langchain_agents.agents.tabular_extraction_agent import TabularExtractionAgent
from app.services.langchain_agents.agents.workflow_orchestrator_agent import WorkflowOrchestratorAgent

__all__ = [
    "ChatReActAgent",
    "TabularExtractionAgent",
    "WorkflowOrchestratorAgent",
]



