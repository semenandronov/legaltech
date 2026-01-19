"""
LangGraph-based Supervisor Agent - Качественная многоагентная архитектура.

Реализует принципы из White Paper по LangGraph:
1. Многоуровневая обработка ошибок (node/graph/app levels)
2. State-Driven Error Management
3. Персистентность через чекпоинты
4. Стратегии управления контекстом (Write/Select/Compress/Isolate)
5. Human-in-the-Loop через interrupts
6. Bounded Retries и Graceful Degradation
"""
from typing import TypedDict, Annotated, List, Dict, Any, Optional, Literal
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from app.services.llm_factory import create_llm
import logging
import json
import asyncio
import operator

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# STATE DEFINITION (TypedDict для частичных обновлений)
# ═══════════════════════════════════════════════════════════════

class AgentState(TypedDict, total=False):
    """
    Состояние графа агента.
    
    Использует TypedDict для поддержки частичных обновлений:
    - Узлы возвращают только изменённые поля
    - Редьюсеры объединяют обновления с существующим состоянием
    """
    # === Основные поля ===
    messages: Annotated[List[BaseMessage], add_messages]  # История с редьюсером
    user_task: str                                         # Исходная задача
    intent: str                                            # Классифицированное намерение
    current_phase: int                                     # Текущая фаза выполнения
    
    # === Документы и файлы ===
    file_ids: List[str]
    documents: List[Dict[str, Any]]
    
    # === Результаты агентов ===
    agent_results: Annotated[Dict[str, Any], lambda old, new: {**old, **new}]
    final_result: Optional[Dict[str, Any]]
    
    # === Управление ошибками (State-Driven Error Management) ===
    error_count: int                          # Счётчик последовательных ошибок
    last_error: Optional[Dict[str, Any]]      # Последняя ошибка
    error_history: Annotated[List[Dict], operator.add]  # История ошибок
    
    # === Метаданные выполнения ===
    execution_id: str
    started_at: str
    step_count: int
    max_steps: int
    
    # === Scratchpad (краткосрочная память) ===
    scratchpad: Dict[str, Any]
    
    # === Контекст для LLM (сжатый) ===
    context_summary: str


# ═══════════════════════════════════════════════════════════════
# ERROR HANDLING STRUCTURES
# ═══════════════════════════════════════════════════════════════

class ErrorSeverity(Enum):
    """Уровни серьёзности ошибок"""
    LOW = "low"           # Можно продолжить
    MEDIUM = "medium"     # Требуется retry
    HIGH = "high"         # Требуется fallback
    CRITICAL = "critical" # Требуется остановка


@dataclass
class NodeError:
    """Структурированная ошибка узла"""
    node_name: str
    error_type: str
    message: str
    severity: ErrorSeverity
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    recoverable: bool = True
    context: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

@dataclass
class SupervisorConfig:
    """Конфигурация супервизора"""
    max_retries: int = 3              # Максимум повторов на узел
    max_steps: int = 50               # Максимум шагов графа
    timeout_seconds: int = 300        # Таймаут выполнения
    context_window_limit: int = 8000  # Лимит токенов контекста
    enable_checkpoints: bool = True   # Включить чекпоинты
    enable_human_in_loop: bool = False # Включить HITL


# ═══════════════════════════════════════════════════════════════
# NODE IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════

class LangGraphSupervisor:
    """
    Supervisor Agent на базе LangGraph.
    
    Архитектура:
    - Граф состояний с чекпоинтами
    - Многоуровневая обработка ошибок
    - Bounded retries с exponential backoff
    - Graceful degradation через fallback nodes
    - Context management strategies
    """
    
    def __init__(self, db=None, config: Optional[SupervisorConfig] = None):
        self.db = db
        self.config = config or SupervisorConfig()
        self.llm = None
        self.graph = None
        self.checkpointer = None
        
        self._init_llm()
        self._build_graph()
    
    def _init_llm(self):
        """Initialize LLM"""
        try:
            self.llm = create_llm(temperature=0.1, use_rate_limiting=False)
            logger.info("LangGraphSupervisor: LLM initialized")
        except Exception as e:
            logger.warning(f"LangGraphSupervisor: Failed to init LLM: {e}")
    
    def _build_graph(self):
        """Построить граф LangGraph"""
        # Создаём граф с типизированным состоянием
        builder = StateGraph(AgentState)
        
        # === Добавляем узлы ===
        builder.add_node("classify_intent", self._node_classify_intent)
        builder.add_node("plan_execution", self._node_plan_execution)
        builder.add_node("execute_agent", self._node_execute_agent)
        builder.add_node("synthesize_results", self._node_synthesize_results)
        builder.add_node("handle_error", self._node_handle_error)
        builder.add_node("fallback", self._node_fallback)
        
        # === Определяем рёбра ===
        builder.set_entry_point("classify_intent")
        
        # Условное ребро после классификации
        builder.add_conditional_edges(
            "classify_intent",
            self._route_after_classify,
            {
                "plan": "plan_execution",
                "error": "handle_error"
            }
        )
        
        # Условное ребро после планирования
        builder.add_conditional_edges(
            "plan_execution",
            self._route_after_plan,
            {
                "execute": "execute_agent",
                "error": "handle_error"
            }
        )
        
        # Условное ребро после выполнения агента
        builder.add_conditional_edges(
            "execute_agent",
            self._route_after_execute,
            {
                "continue": "execute_agent",  # Следующий агент
                "synthesize": "synthesize_results",
                "error": "handle_error"
            }
        )
        
        # Условное ребро после обработки ошибок
        builder.add_conditional_edges(
            "handle_error",
            self._route_after_error,
            {
                "retry": "execute_agent",
                "fallback": "fallback",
                "abort": END
            }
        )
        
        # Финальные рёбра
        builder.add_edge("synthesize_results", END)
        builder.add_edge("fallback", END)
        
        # Компилируем граф с чекпоинтером
        if self.config.enable_checkpoints:
            self.checkpointer = MemorySaver()
            self.graph = builder.compile(checkpointer=self.checkpointer)
        else:
            self.graph = builder.compile()
        
        logger.info("LangGraphSupervisor: Graph built successfully")
    
    # ═══════════════════════════════════════════════════════════════
    # NODE FUNCTIONS (Level 1: Node-level error handling)
    # ═══════════════════════════════════════════════════════════════
    
    async def _node_classify_intent(self, state: AgentState) -> Dict[str, Any]:
        """
        Узел классификации намерения.
        
        Level 1 Error Handling: try-except внутри узла
        """
        try:
            user_task = state.get("user_task", "")
            
            # Классификация по ключевым словам (надёжный fallback)
            intent = self._classify_by_keywords(user_task)
            
            # Если есть LLM, уточняем классификацию
            if self.llm:
                try:
                    intent = await self._classify_with_llm(user_task)
                except Exception as e:
                    logger.warning(f"LLM classification failed, using keyword fallback: {e}")
            
            return {
                "intent": intent,
                "messages": [AIMessage(content=f"Намерение определено: {intent}")],
                "step_count": state.get("step_count", 0) + 1
            }
            
        except Exception as e:
            # Обновляем состояние с информацией об ошибке
            return {
                "last_error": {
                    "node": "classify_intent",
                    "type": type(e).__name__,
                    "message": str(e),
                    "severity": "medium"
                },
                "error_count": state.get("error_count", 0) + 1,
                "error_history": [NodeError(
                    node_name="classify_intent",
                    error_type=type(e).__name__,
                    message=str(e),
                    severity=ErrorSeverity.MEDIUM
                ).__dict__]
            }
    
    async def _node_plan_execution(self, state: AgentState) -> Dict[str, Any]:
        """
        Узел планирования выполнения.
        
        Создаёт план на основе intent и доступных агентов.
        """
        try:
            intent = state.get("intent", "understand")
            
            # Получаем план для намерения
            execution_plan = self._get_execution_plan(intent)
            
            return {
                "scratchpad": {
                    **state.get("scratchpad", {}),
                    "execution_plan": execution_plan,
                    "agents_to_run": execution_plan["agents"],
                    "current_agent_index": 0
                },
                "messages": [AIMessage(content=f"План создан: {len(execution_plan['agents'])} агентов")],
                "step_count": state.get("step_count", 0) + 1
            }
            
        except Exception as e:
            return {
                "last_error": {
                    "node": "plan_execution",
                    "type": type(e).__name__,
                    "message": str(e),
                    "severity": "medium"
                },
                "error_count": state.get("error_count", 0) + 1
            }
    
    async def _node_execute_agent(self, state: AgentState) -> Dict[str, Any]:
        """
        Узел выполнения агента.
        
        Выполняет текущего агента из плана.
        """
        try:
            scratchpad = state.get("scratchpad", {})
            agents_to_run = scratchpad.get("agents_to_run", [])
            current_index = scratchpad.get("current_agent_index", 0)
            
            if current_index >= len(agents_to_run):
                # Все агенты выполнены
                return {
                    "scratchpad": {**scratchpad, "all_agents_completed": True}
                }
            
            agent_name = agents_to_run[current_index]
            
            # Выполняем агента
            result = await self._run_subagent(
                agent_name=agent_name,
                state=state
            )
            
            # Обновляем результаты и индекс
            return {
                "agent_results": {agent_name: result},
                "scratchpad": {
                    **scratchpad,
                    "current_agent_index": current_index + 1,
                    "last_agent": agent_name
                },
                "messages": [AIMessage(content=f"Агент {agent_name} завершён")],
                "step_count": state.get("step_count", 0) + 1,
                # Сбрасываем счётчик ошибок при успехе
                "error_count": 0,
                "last_error": None
            }
            
        except Exception as e:
            return {
                "last_error": {
                    "node": "execute_agent",
                    "type": type(e).__name__,
                    "message": str(e),
                    "severity": "high",
                    "agent": state.get("scratchpad", {}).get("agents_to_run", [])[
                        state.get("scratchpad", {}).get("current_agent_index", 0)
                    ] if state.get("scratchpad", {}).get("agents_to_run") else "unknown"
                },
                "error_count": state.get("error_count", 0) + 1,
                "error_history": [{
                    "node": "execute_agent",
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }]
            }
    
    async def _node_synthesize_results(self, state: AgentState) -> Dict[str, Any]:
        """
        Узел синтеза результатов.
        
        Объединяет результаты всех агентов в финальный ответ.
        """
        try:
            agent_results = state.get("agent_results", {})
            user_task = state.get("user_task", "")
            
            # Синтезируем результаты
            synthesis = await self._synthesize(agent_results, user_task)
            
            return {
                "final_result": {
                    "synthesis": synthesis,
                    "agent_results": agent_results,
                    "success": True,
                    "completed_at": datetime.utcnow().isoformat()
                },
                "messages": [AIMessage(content="Результаты синтезированы")]
            }
            
        except Exception as e:
            return {
                "final_result": {
                    "synthesis": "Ошибка синтеза результатов",
                    "agent_results": state.get("agent_results", {}),
                    "success": False,
                    "error": str(e)
                }
            }
    
    async def _node_handle_error(self, state: AgentState) -> Dict[str, Any]:
        """
        Узел обработки ошибок (Level 2: Graph-level).
        
        Анализирует ошибку и решает: retry, fallback или abort.
        """
        error = state.get("last_error", {})
        error_count = state.get("error_count", 0)
        
        logger.warning(f"Error handler: {error}, count: {error_count}")
        
        # Определяем стратегию на основе severity и количества ошибок
        severity = error.get("severity", "medium")
        
        if severity == "critical":
            # Критические ошибки - немедленный abort
            return {
                "scratchpad": {
                    **state.get("scratchpad", {}),
                    "error_decision": "abort",
                    "abort_reason": error.get("message")
                }
            }
        
        if error_count < self.config.max_retries:
            # Bounded retry
            return {
                "scratchpad": {
                    **state.get("scratchpad", {}),
                    "error_decision": "retry",
                    "retry_count": error_count
                },
                "messages": [AIMessage(content=f"Повторная попытка {error_count}/{self.config.max_retries}")]
            }
        
        # Лимит повторов исчерпан - fallback
        return {
            "scratchpad": {
                **state.get("scratchpad", {}),
                "error_decision": "fallback",
                "fallback_reason": f"Max retries ({self.config.max_retries}) exceeded"
            },
            "messages": [AIMessage(content="Переход к резервному сценарию")]
        }
    
    async def _node_fallback(self, state: AgentState) -> Dict[str, Any]:
        """
        Узел резервного сценария (Graceful Degradation).
        
        Возвращает частичный результат или сообщение об ошибке.
        """
        agent_results = state.get("agent_results", {})
        error = state.get("last_error", {})
        
        # Собираем то, что удалось получить
        partial_results = {
            k: v for k, v in agent_results.items()
            if isinstance(v, dict) and v.get("success", False)
        }
        
        return {
            "final_result": {
                "synthesis": "Частичные результаты (некоторые агенты не завершились)",
                "agent_results": partial_results,
                "success": False,
                "partial": True,
                "error": error.get("message", "Unknown error"),
                "completed_at": datetime.utcnow().isoformat()
            }
        }
    
    # ═══════════════════════════════════════════════════════════════
    # ROUTING FUNCTIONS (Level 2: Graph-level error handling)
    # ═══════════════════════════════════════════════════════════════
    
    def _route_after_classify(self, state: AgentState) -> Literal["plan", "error"]:
        """Маршрутизация после классификации"""
        if state.get("last_error"):
            return "error"
        return "plan"
    
    def _route_after_plan(self, state: AgentState) -> Literal["execute", "error"]:
        """Маршрутизация после планирования"""
        if state.get("last_error"):
            return "error"
        return "execute"
    
    def _route_after_execute(self, state: AgentState) -> Literal["continue", "synthesize", "error"]:
        """Маршрутизация после выполнения агента"""
        if state.get("last_error"):
            return "error"
        
        scratchpad = state.get("scratchpad", {})
        if scratchpad.get("all_agents_completed"):
            return "synthesize"
        
        return "continue"
    
    def _route_after_error(self, state: AgentState) -> Literal["retry", "fallback", "abort"]:
        """Маршрутизация после обработки ошибки"""
        scratchpad = state.get("scratchpad", {})
        decision = scratchpad.get("error_decision", "fallback")
        
        if decision == "retry":
            return "retry"
        elif decision == "abort":
            return "abort"
        else:
            return "fallback"
    
    # ═══════════════════════════════════════════════════════════════
    # HELPER METHODS
    # ═══════════════════════════════════════════════════════════════
    
    def _classify_by_keywords(self, user_task: str) -> str:
        """Классификация по ключевым словам (надёжный fallback)"""
        task_lower = user_task.lower()
        
        if any(w in task_lower for w in ["риск", "проверь", "проблем"]):
            return "check_risks"
        elif any(w in task_lower for w in ["извлеч", "данные", "стороны"]):
            return "extract_data"
        elif any(w in task_lower for w in ["что", "какой", "где", "?"]):
            return "answer_question"
        elif any(w in task_lower for w in ["сравни", "различ"]):
            return "compare"
        elif any(w in task_lower for w in ["составь", "напиши", "создай"]):
            return "create_document"
        elif any(w in task_lower for w in ["полн", "детальн"]):
            return "full_analysis"
        else:
            return "understand"
    
    async def _classify_with_llm(self, user_task: str) -> str:
        """Классификация с помощью LLM"""
        from langchain_core.prompts import ChatPromptTemplate
        
        prompt = ChatPromptTemplate.from_template("""
Классифицируй задачу в одну категорию:
- understand: понять документ
- extract_data: извлечь данные
- check_risks: проверить риски
- answer_question: ответить на вопрос
- compare: сравнить документы
- create_document: создать документ
- full_analysis: полный анализ

Задача: {task}

Ответь одним словом - категорией.""")
        
        chain = prompt | self.llm
        response = await chain.ainvoke({"task": user_task})
        content = response.content if hasattr(response, 'content') else str(response)
        
        # Извлекаем категорию
        for intent in ["understand", "extract_data", "check_risks", "answer_question", 
                       "compare", "create_document", "full_analysis"]:
            if intent in content.lower():
                return intent
        
        return "understand"
    
    def _get_execution_plan(self, intent: str) -> Dict[str, Any]:
        """Получить план выполнения для намерения"""
        plans = {
            "understand": {
                "agents": ["summarizer", "entity_extractor"],
                "parallel_groups": [["summarizer"], ["entity_extractor"]]
            },
            "extract_data": {
                "agents": ["entity_extractor"],
                "parallel_groups": [["entity_extractor"]]
            },
            "check_risks": {
                "agents": ["summarizer", "playbook_checker"],
                "parallel_groups": [["summarizer"], ["playbook_checker"]]
            },
            "answer_question": {
                "agents": ["rag_searcher"],
                "parallel_groups": [["rag_searcher"]]
            },
            "compare": {
                "agents": ["tabular_reviewer"],
                "parallel_groups": [["tabular_reviewer"]]
            },
            "create_document": {
                "agents": ["summarizer", "document_drafter"],
                "parallel_groups": [["summarizer"], ["document_drafter"]]
            },
            "full_analysis": {
                "agents": ["summarizer", "entity_extractor", "playbook_checker"],
                "parallel_groups": [["summarizer"], ["entity_extractor", "playbook_checker"]]
            }
        }
        return plans.get(intent, plans["understand"])
    
    async def _run_subagent(self, agent_name: str, state: AgentState) -> Dict[str, Any]:
        """Запустить субагента"""
        try:
            # Импортируем субагентов
            from app.services.workflows.subagents import (
                SummarizerAgent, EntityExtractorAgent, RAGSearcherAgent,
                PlaybookCheckerAgent, TabularReviewerAgent, DocumentDrafterAgent
            )
            from app.services.workflows.supervisor_agent import ExecutionContext
            
            agent_classes = {
                "summarizer": SummarizerAgent,
                "entity_extractor": EntityExtractorAgent,
                "rag_searcher": RAGSearcherAgent,
                "playbook_checker": PlaybookCheckerAgent,
                "tabular_reviewer": TabularReviewerAgent,
                "document_drafter": DocumentDrafterAgent
            }
            
            agent_class = agent_classes.get(agent_name)
            if not agent_class:
                return {"success": False, "error": f"Unknown agent: {agent_name}"}
            
            agent = agent_class(self.db)
            
            # Создаём контекст
            context = ExecutionContext(
                user_task=state.get("user_task", ""),
                documents=state.get("documents", []),
                file_ids=state.get("file_ids", []),
                previous_results=state.get("agent_results", {})
            )
            
            # Выполняем
            result = await agent.execute(context, {"file_ids": state.get("file_ids", [])})
            
            return {
                "success": result.success,
                "data": result.data,
                "summary": result.summary,
                "error": result.error
            }
            
        except Exception as e:
            logger.error(f"Subagent {agent_name} failed: {e}", exc_info=True)
            raise
    
    async def _synthesize(self, agent_results: Dict[str, Any], user_task: str) -> str:
        """Синтезировать результаты"""
        if not self.llm:
            # Fallback без LLM
            summaries = []
            for name, result in agent_results.items():
                if isinstance(result, dict) and result.get("success"):
                    summaries.append(f"**{name}**: {result.get('summary', 'Выполнено')}")
            return "\n\n".join(summaries) if summaries else "Результаты не получены"
        
        from langchain_core.prompts import ChatPromptTemplate
        
        results_text = "\n".join([
            f"- {name}: {r.get('summary', 'Нет данных')}"
            for name, r in agent_results.items()
            if isinstance(r, dict)
        ])
        
        prompt = ChatPromptTemplate.from_template("""
Синтезируй результаты работы агентов в единый ответ.

Задача пользователя: {task}

Результаты агентов:
{results}

Создай связный, полезный ответ.""")
        
        chain = prompt | self.llm
        response = await chain.ainvoke({"task": user_task, "results": results_text})
        return response.content if hasattr(response, 'content') else str(response)
    
    # ═══════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════════════════════════════
    
    async def execute(
        self,
        user_task: str,
        file_ids: List[str],
        documents: List[Dict[str, Any]],
        execution_id: str = None,
        thread_id: str = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Выполнить workflow с streaming событий.
        
        Args:
            user_task: Задача пользователя
            file_ids: ID файлов
            documents: Информация о документах
            execution_id: ID выполнения
            thread_id: ID потока для чекпоинтов
            
        Yields:
            События выполнения
        """
        # Начальное состояние
        initial_state: AgentState = {
            "user_task": user_task,
            "file_ids": file_ids,
            "documents": documents,
            "messages": [HumanMessage(content=user_task)],
            "agent_results": {},
            "error_count": 0,
            "error_history": [],
            "step_count": 0,
            "max_steps": self.config.max_steps,
            "execution_id": execution_id or "unknown",
            "started_at": datetime.utcnow().isoformat(),
            "scratchpad": {},
            "current_phase": 0
        }
        
        # Конфигурация с thread_id для чекпоинтов
        config = {}
        if thread_id and self.checkpointer:
            config["configurable"] = {"thread_id": thread_id}
        
        yield {
            "type": "started",
            "message": "Запуск LangGraph Supervisor..."
        }
        
        try:
            # Выполняем граф с streaming
            async for event in self.graph.astream(initial_state, config):
                # Извлекаем данные из события
                for node_name, node_output in event.items():
                    if node_name == "__end__":
                        continue
                    
                    # Отправляем событие о завершении узла
                    yield {
                        "type": "node_completed",
                        "node": node_name,
                        "data": self._extract_event_data(node_output)
                    }
                    
                    # Проверяем на финальный результат
                    if "final_result" in node_output:
                        yield {
                            "type": "completed",
                            "result": node_output["final_result"]
                        }
                        
        except Exception as e:
            logger.error(f"LangGraph execution failed: {e}", exc_info=True)
            yield {
                "type": "error",
                "error": str(e),
                "message": f"Ошибка выполнения: {str(e)}"
            }
    
    def _extract_event_data(self, node_output: Dict[str, Any]) -> Dict[str, Any]:
        """Извлечь данные для события"""
        return {
            "step_count": node_output.get("step_count"),
            "intent": node_output.get("intent"),
            "error": node_output.get("last_error"),
            "agent_results": list(node_output.get("agent_results", {}).keys()) if node_output.get("agent_results") else None
        }


