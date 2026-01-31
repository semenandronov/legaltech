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

graphs/subgraphs/ — Sub-graphs для модульности
  - file_extraction: Извлечение из одного файла
  - rag_retrieval: RAG поиск
  - garant_retrieval: Поиск в ГАРАНТ
  - thinking: Пошаговое мышление

nodes/ — Узлы (простые функции без циклов)
  - discrepancy_risk_node: Объединённый узел противоречий + рисков
  - summary_chain: Упрощённый summary как chain

utils/ — Утилиты для графов
  - reducers: Кастомные reducers для state
  - message_utils: Фильтрация и обрезка сообщений
  - streaming: Утилиты для стриминга
  - time_travel: Отладка и replay
  - breakpoints: Конфигурация breakpoints
  - state_editing: Редактирование состояния

memory/ — Долгосрочная память
  - schemas: Pydantic схемы для профилей и памяти
  - store: MemoryStore для персистентности
  - updaters: LLM-based обновление памяти
  - trustcall: Извлечение и валидация JSON

assistants/ — Преднастроенные assistants
  - legal-assistant: Общий юридический ассистент
  - deep-analyst: Глубокий анализ
  - document-drafter: Составление документов
  - tabular-extractor: Извлечение в таблицы
  - workflow-orchestrator: Оркестратор workflows

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

# Legacy для обратной совместимости
from app.services.langchain_agents.legacy_stubs import (
    AgentCoordinator,
    AnalysisState,
)

# Utils
from app.services.langchain_agents.utils.reducers import (
    merge_dicts_reducer,
    append_unique_reducer,
    sort_by_confidence_reducer,
    merge_citations_reducer,
    append_errors_reducer,
)
from app.services.langchain_agents.utils.message_utils import (
    filter_messages_by_count,
    trim_messages_by_tokens,
    summarize_old_messages,
)
from app.services.langchain_agents.utils.streaming import (
    StreamEvent,
    format_sse_event,
    stream_graph_with_mode,
    stream_tokens,
)
from app.services.langchain_agents.utils.time_travel import (
    get_state_history,
    replay_from_checkpoint,
    fork_checkpoint,
)
from app.services.langchain_agents.utils.breakpoints import (
    BreakpointConfig,
    NodeInterrupt,
)
from app.services.langchain_agents.utils.state_editing import (
    update_graph_state,
    edit_message_in_state,
)

# Memory
from app.services.langchain_agents.memory import (
    UserProfile,
    CaseMemory,
    QueryRecord,
    Insight,
    MemoryStore,
    get_memory_store,
    update_user_profile,
    update_case_memory,
    extract_insights,
    TrustcallExtractor,
    extract_and_validate,
    update_with_patch,
)

# Assistants
from app.services.langchain_agents.assistants import (
    AssistantConfig,
    get_assistant,
    list_assistants,
)

# Subgraphs
from app.services.langchain_agents.graphs.subgraphs import (
    create_rag_retrieval_subgraph,
    create_garant_retrieval_subgraph,
    create_thinking_subgraph,
    create_file_extraction_subgraph,
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
    
    # Legacy для обратной совместимости
    "AgentCoordinator",
    "AnalysisState",
    
    # Utils - Reducers
    "merge_dicts_reducer",
    "append_unique_reducer",
    "sort_by_confidence_reducer",
    "merge_citations_reducer",
    "append_errors_reducer",
    
    # Utils - Message
    "filter_messages_by_count",
    "trim_messages_by_tokens",
    "summarize_old_messages",
    
    # Utils - Streaming
    "StreamEvent",
    "format_sse_event",
    "stream_graph_with_mode",
    "stream_tokens",
    
    # Utils - Time Travel
    "get_state_history",
    "replay_from_checkpoint",
    "fork_checkpoint",
    
    # Utils - Breakpoints
    "BreakpointConfig",
    "NodeInterrupt",
    
    # Utils - State Editing
    "update_graph_state",
    "edit_message_in_state",
    
    # Memory
    "UserProfile",
    "CaseMemory",
    "QueryRecord",
    "Insight",
    "MemoryStore",
    "get_memory_store",
    "update_user_profile",
    "update_case_memory",
    "extract_insights",
    "TrustcallExtractor",
    "extract_and_validate",
    "update_with_patch",
    
    # Assistants
    "AssistantConfig",
    "get_assistant",
    "list_assistants",
    
    # Subgraphs
    "create_rag_retrieval_subgraph",
    "create_garant_retrieval_subgraph",
    "create_thinking_subgraph",
    "create_file_extraction_subgraph",
]
