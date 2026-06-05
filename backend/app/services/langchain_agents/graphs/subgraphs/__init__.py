"""
Sub-graphs для LangGraph.

Sub-graphs обеспечивают:
- Модульность и переиспользование
- Изоляцию состояния
- Чистые traces в LangSmith
- Параллельное выполнение через Send API

Доступные sub-graphs:
- rag_retrieval: RAG поиск в документах дела
- thinking: Пошаговое мышление (deep_think)

# ИСПОЛЬЗОВАНИЕ
```python
from app.services.langchain_agents.graphs.subgraphs import (
    create_rag_retrieval_subgraph,
    create_garant_retrieval_subgraph,
    create_thinking_subgraph,
)

# Создание subgraph
rag_subgraph = create_rag_retrieval_subgraph(rag_service, db)

# Использование с Send API
from langgraph.types import Send

def dispatch_retrievals(state):
    return [
        Send("rag_retrieval", {"query": state["question"], "case_id": state["case_id"]}),
        Send("garant_retrieval", {"query": state["question"]})
    ]
```
"""

from app.services.langchain_agents.graphs.subgraphs.rag_retrieval import (
    RAGRetrievalState,
    create_rag_retrieval_subgraph,
    create_initial_rag_state,
)

from app.services.langchain_agents.graphs.subgraphs.thinking import (
    ThinkingState,
    ThinkingStep,
    create_thinking_subgraph,
    create_initial_thinking_state,
)

__all__ = [
    # RAG Retrieval
    "RAGRetrievalState",
    "create_rag_retrieval_subgraph",
    "create_initial_rag_state",
    # Thinking
    "ThinkingState",
    "ThinkingStep",
    "create_thinking_subgraph",
    "create_initial_thinking_state",
]
