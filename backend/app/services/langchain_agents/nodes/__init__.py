"""
Nodes module - узлы для LangGraph с линейной обработкой.

Согласно LangGraph документации, узел (node) - это простая функция обработки без:
- Принятия решений о следующем действии
- Циклов или итераций
- Условной логики (кроме простых if/else)

Узлы в этом модуле:
- discrepancy_risk_node: Поиск противоречий + оценка рисков (объединено)
- summary_chain: Генерация резюме (упрощено до chain)
"""

from app.services.langchain_agents.nodes.discrepancy_risk_node import discrepancy_risk_node
from app.services.langchain_agents.nodes.summary_chain import create_summary_chain, summary_chain_node

__all__ = [
    "discrepancy_risk_node",
    "create_summary_chain",
    "summary_chain_node",
]
