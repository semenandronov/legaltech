"""
WorkflowGraph - LangGraph граф для страницы Workflows.

# РОЛЬ
Граф-оркестратор для выполнения сложных многошаговых workflows
с планированием, параллельным выполнением и адаптацией при ошибках.

# ПАТТЕРН: Планирование + Параллельное выполнение
1. Анализ: Определение структуры workflow
2. Планирование: Генерация оптимального плана
3. HITL: Одобрение плана пользователем (опционально)
4. Выполнение: Параллельное выполнение независимых шагов
5. Мониторинг: Отслеживание прогресса
6. Адаптация: Обработка ошибок
7. Синтез: Объединение результатов

# АРХИТЕКТУРА ГРАФА
```
START
  ↓
analyze (анализ workflow definition)
  ↓
generate_plan (генерация плана шагов)
  ↓
  ├── require_approval=True → approval_interrupt (HITL)
  │                                ↓
  │                           [user approval]
  │                                ↓
  └── require_approval=False ──────┘
                                   ↓
                            execute_steps (по уровням зависимостей)
                                   ↓
                              monitor (отслеживание)
                                   ↓
                              synthesize (объединение)
                                   ↓
                                  END
```

# КОГДА ИСПОЛЬЗОВАТЬ
- Сложные задачи с 3+ зависимыми шагами
- Нужна координация нескольких типов анализа
- Важен контроль пользователя над планом
- Требуется автоматическая адаптация при ошибках

# КОГДА НЕ ИСПОЛЬЗОВАТЬ
- Простой вопрос-ответ → используй ChatGraph
- Извлечение в таблицу → используй TabularGraph
"""
from typing import TypedDict, Literal, Optional, List, Dict, Any, Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Send
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from app.services.llm_factory import create_llm
from app.services.rag_service import RAGService
from app.utils.checkpointer_setup import get_checkpointer_instance
from app.services.langchain_agents.store_integration import get_store_instance
from app.services.langchain_agents.utils.reducers import (
    merge_dicts_reducer,
    append_unique_reducer,
    append_errors_reducer,
)
from sqlalchemy.orm import Session
import logging
import json

logger = logging.getLogger(__name__)


# ============== State Definition ==============

# Input Schema - только входные данные
class WorkflowGraphInputState(TypedDict):
    """
    Входное состояние графа Workflow.
    
    Содержит только данные, необходимые для начала обработки.
    """
    workflow_id: str
    case_id: str
    user_id: str
    workflow_definition: Dict[str, Any]
    require_approval: bool
    max_parallel_steps: int
    auto_adapt: bool


# Output Schema - только результаты
class WorkflowGraphOutputState(TypedDict):
    """
    Выходное состояние графа Workflow.
    
    Содержит только финальные результаты.
    """
    final_result: Optional[Dict[str, Any]]
    execution_stats: Optional[Dict[str, Any]]
    step_errors: List[Dict[str, Any]]
    current_phase: str


# Full State - полное внутреннее состояние
class WorkflowGraphState(TypedDict):
    """
    Состояние графа Workflow.
    
    Использует кастомные редьюсеры для:
    - messages: стандартный operator.add для конкатенации
    - step_results: merge_dicts_reducer для объединения результатов шагов
    - step_errors: append_unique_reducer для накопления ошибок без дубликатов
    """
    # Входные данные
    workflow_id: str
    case_id: str
    user_id: str
    workflow_definition: Dict[str, Any]
    
    # Опции
    require_approval: bool
    max_parallel_steps: int
    auto_adapt: bool
    
    # План
    plan: Optional[Dict[str, Any]]
    plan_approved: bool
    plan_modifications: Optional[Dict[str, Any]]
    
    # Выполнение
    current_level: int
    step_results: Annotated[Dict[str, Any], merge_dicts_reducer]
    step_errors: Annotated[List[Dict[str, Any]], append_unique_reducer]
    
    # Мониторинг
    execution_stats: Optional[Dict[str, Any]]
    
    # Результат
    final_result: Optional[Dict[str, Any]]
    
    # Метаданные
    messages: Annotated[List[BaseMessage], add_messages]  # add_messages поддерживает RemoveMessage и перезапись по ID
    current_phase: str


def create_initial_workflow_state(
    workflow_id: str,
    case_id: str,
    user_id: str,
    workflow_definition: Dict[str, Any],
    require_approval: bool = True,
    max_parallel_steps: int = 3,
    auto_adapt: bool = True
) -> WorkflowGraphState:
    """Создать начальное состояние для графа Workflow."""
    return WorkflowGraphState(
        workflow_id=workflow_id,
        case_id=case_id,
        user_id=user_id,
        workflow_definition=workflow_definition,
        require_approval=require_approval,
        max_parallel_steps=max_parallel_steps,
        auto_adapt=auto_adapt,
        plan=None,
        plan_approved=False,
        plan_modifications=None,
        current_level=0,
        step_results={},
        step_errors=[],
        execution_stats=None,
        final_result=None,
        messages=[HumanMessage(content=f"Запуск workflow: {workflow_definition.get('name', 'Unnamed')}")],
        current_phase="init"
    )


# ============== Node Functions ==============

def analyze_node(state: WorkflowGraphState, db: Session = None) -> WorkflowGraphState:
    """
    Узел анализа workflow.
    
    Анализирует определение workflow и готовит данные для планирования.
    """
    logger.info(f"[WorkflowGraph] Analyzing workflow {state['workflow_id']}")
    
    new_state = dict(state)
    new_state["current_phase"] = "analyze"
    
    definition = state["workflow_definition"]
    
    # Анализируем структуру
    steps = definition.get("steps", [])
    
    # Определяем зависимости
    step_ids = {s.get("id") for s in steps}
    has_dependencies = any(s.get("dependencies") for s in steps)
    
    # Определяем возможности параллелизации
    independent_steps = [s for s in steps if not s.get("dependencies")]
    
    analysis = {
        "name": definition.get("name", "Unnamed"),
        "description": definition.get("description", ""),
        "total_steps": len(steps),
        "has_dependencies": has_dependencies,
        "independent_steps_count": len(independent_steps),
        "can_parallelize": len(independent_steps) > 1,
        "step_types": list(set(s.get("type", "custom") for s in steps))
    }
    
    new_state["execution_stats"] = {"analysis": analysis}
    new_state["messages"] = [AIMessage(
        content=f"📊 Анализ workflow: {len(steps)} шагов, {len(independent_steps)} независимых"
    )]
    
    logger.info(f"[WorkflowGraph] Analysis complete: {analysis}")
    return new_state


def generate_plan_node(state: WorkflowGraphState, db: Session = None) -> WorkflowGraphState:
    """
    Узел генерации плана выполнения.
    """
    logger.info(f"[WorkflowGraph] Generating plan for workflow {state['workflow_id']}")
    
    new_state = dict(state)
    new_state["current_phase"] = "generate_plan"
    
    definition = state["workflow_definition"]
    steps = definition.get("steps", [])
    
    # Группируем шаги по уровням зависимостей
    levels = _group_steps_by_dependency_level(steps)
    
    # Оцениваем время выполнения
    time_estimates = {
        "analysis": 3,
        "extraction": 5,
        "generation": 4,
        "review": 2,
        "custom": 3
    }
    
    total_time = 0
    for level in levels:
        level_time = max(time_estimates.get(s.get("type", "custom"), 3) for s in level)
        total_time += level_time
    
    plan = {
        "workflow_id": state["workflow_id"],
        "name": definition.get("name"),
        "description": definition.get("description"),
        "levels": [
            {
                "level": i,
                "steps": [
                    {
                        "id": s.get("id"),
                        "name": s.get("name"),
                        "type": s.get("type", "custom"),
                        "description": s.get("description", ""),
                        "dependencies": s.get("dependencies", []),
                        "config": s.get("config", {})
                    }
                    for s in level
                ],
                "parallel": len(level) > 1
            }
            for i, level in enumerate(levels)
        ],
        "estimated_time_minutes": total_time,
        "total_steps": len(steps)
    }
    
    new_state["plan"] = plan
    new_state["messages"] = [AIMessage(
        content=f"📋 План сгенерирован: {len(levels)} уровней, ~{total_time} минут"
    )]
    
    logger.info(f"[WorkflowGraph] Plan generated: {len(levels)} levels")
    return new_state


def _group_steps_by_dependency_level(steps: List[Dict]) -> List[List[Dict]]:
    """Группировать шаги по уровням зависимостей."""
    levels = []
    completed_ids = set()
    remaining_steps = list(steps)
    
    while remaining_steps:
        current_level = []
        for step in remaining_steps[:]:
            deps = step.get("dependencies", [])
            if all(dep in completed_ids for dep in deps):
                current_level.append(step)
                remaining_steps.remove(step)
        
        if not current_level:
            # Циклическая зависимость - добавляем оставшиеся
            current_level = remaining_steps
            remaining_steps = []
        
        levels.append(current_level)
        completed_ids.update(s.get("id") for s in current_level)
    
    return levels


def approval_interrupt_node(state: WorkflowGraphState) -> WorkflowGraphState:
    """
    Узел HITL для одобрения плана.
    """
    from langgraph.types import interrupt
    
    logger.info("[WorkflowGraph] Requesting plan approval")
    
    new_state = dict(state)
    new_state["current_phase"] = "approval"
    
    plan = state.get("plan", {})
    
    # Формируем payload для interrupt
    interrupt_payload = {
        "type": "workflow_plan_approval",
        "workflow_id": state["workflow_id"],
        "plan": plan,
        "message": f"Одобрите план выполнения workflow '{plan.get('name')}'"
    }
    
    # Прерываем выполнение
    interrupt(interrupt_payload)
    
    return new_state


def apply_approval_node(state: WorkflowGraphState) -> WorkflowGraphState:
    """
    Узел применения решения по одобрению.
    """
    logger.info("[WorkflowGraph] Applying approval decision")
    
    new_state = dict(state)
    new_state["current_phase"] = "apply_approval"
    
    # После resume состояние должно содержать plan_approved и plan_modifications
    if state.get("plan_approved"):
        new_state["messages"] = [AIMessage(content="✅ План одобрен, начинаю выполнение")]
    else:
        new_state["messages"] = [AIMessage(content="❌ План отклонён")]
    
    # Применяем модификации если есть
    modifications = state.get("plan_modifications", {})
    if modifications:
        plan = dict(state.get("plan", {}))
        for level in plan.get("levels", []):
            for step in level.get("steps", []):
                step_mods = modifications.get(step["id"], {})
                if step_mods.get("skip"):
                    step["status"] = "skipped"
                if step_mods.get("config"):
                    step["config"].update(step_mods["config"])
        new_state["plan"] = plan
    
    return new_state


def dispatch_parallel_steps_node(state: WorkflowGraphState) -> List[Send]:
    """
    Узел диспетчеризации параллельных шагов через Send API.
    
    Создаёт Send для каждого шага текущего уровня, что позволяет
    выполнять независимые шаги параллельно.
    """
    current_level = state.get("current_level", 0)
    plan = state.get("plan", {})
    levels = plan.get("levels", [])
    
    if current_level >= len(levels):
        logger.info("[WorkflowGraph] All levels completed, no steps to dispatch")
        return []
    
    level_data = levels[current_level]
    steps = level_data.get("steps", [])
    
    logger.info(f"[WorkflowGraph] Dispatching {len(steps)} steps via Send API for level {current_level}")
    
    # Создаём Send для каждого шага
    sends = []
    for step_data in steps:
        if step_data.get("status") == "skipped":
            continue
        
        sends.append(
            Send(
                "execute_single_step",
                {
                    "step_data": step_data,
                    "workflow_id": state["workflow_id"],
                    "case_id": state["case_id"],
                    "user_id": state["user_id"],
                    "workflow_definition": state["workflow_definition"],
                    "step_results": state.get("step_results", {}),
                    "max_parallel_steps": state.get("max_parallel_steps", 3),
                    "auto_adapt": state.get("auto_adapt", True),
                }
            )
        )
    
    return sends


def execute_single_step_node(
    state: Dict[str, Any],
    db: Session = None,
    rag_service: RAGService = None
) -> Dict[str, Any]:
    """
    Узел выполнения одного шага workflow.
    
    Вызывается параллельно для каждого шага через Send API.
    """
    step_data = state.get("step_data", {})
    step_id = step_data.get("id")
    
    logger.info(f"[WorkflowGraph] Executing step {step_id}: {step_data.get('name')}")
    
    try:
        from app.services.langchain_agents.agents.workflow_orchestrator_agent import (
            WorkflowOrchestratorAgent,
            WorkflowOrchestratorConfig,
            WorkflowStep
        )
        
        config = WorkflowOrchestratorConfig(
            workflow_id=state["workflow_id"],
            case_id=state["case_id"],
            user_id=state["user_id"],
            workflow_definition=state["workflow_definition"],
            max_parallel_steps=state.get("max_parallel_steps", 3),
            require_plan_approval=False,
            auto_adapt=state.get("auto_adapt", True)
        )
        
        orchestrator = WorkflowOrchestratorAgent(config, db, rag_service)
        orchestrator.results = state.get("step_results", {})
        
        step = WorkflowStep(
            id=step_data["id"],
            name=step_data["name"],
            description=step_data.get("description", ""),
            step_type=step_data.get("type", "custom"),
            dependencies=step_data.get("dependencies", []),
            config=step_data.get("config", {})
        )
        
        import asyncio
        
        async def do_execute():
            return await orchestrator.execute_step(step)
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, do_execute())
                    result = future.result(timeout=120)
            else:
                result = loop.run_until_complete(do_execute())
        except RuntimeError:
            result = asyncio.run(do_execute())
        
        return {
            "step_results": {step_id: result},
            "step_errors": [],
            "current_phase": f"step_{step_id}_complete"
        }
        
    except Exception as e:
        logger.error(f"[WorkflowGraph] Step {step_id} error: {e}", exc_info=True)
        return {
            "step_results": {},
            "step_errors": [{"step_id": step_id, "error": str(e)}],
            "current_phase": f"step_{step_id}_error"
        }


def execute_level_node(state: WorkflowGraphState, db: Session = None, rag_service: RAGService = None) -> WorkflowGraphState:
    """
    Узел выполнения одного уровня шагов (fallback без Send API).
    
    Используется когда Send API недоступен или для простых workflow.
    """
    current_level = state.get("current_level", 0)
    plan = state.get("plan", {})
    levels = plan.get("levels", [])
    
    if current_level >= len(levels):
        logger.info("[WorkflowGraph] All levels completed")
        new_state = dict(state)
        new_state["current_phase"] = "complete"
        return new_state
    
    level_data = levels[current_level]
    steps = level_data.get("steps", [])
    
    logger.info(f"[WorkflowGraph] Executing level {current_level}: {[s['name'] for s in steps]} (sequential mode)")
    
    new_state = dict(state)
    new_state["current_phase"] = f"execute_level_{current_level}"
    
    from app.services.langchain_agents.agents.workflow_orchestrator_agent import (
        WorkflowOrchestratorAgent,
        WorkflowOrchestratorConfig,
        WorkflowStep
    )
    
    step_results = dict(state.get("step_results", {}))
    step_errors = list(state.get("step_errors", []))
    
    # Создаём оркестратор для выполнения шагов
    config = WorkflowOrchestratorConfig(
        workflow_id=state["workflow_id"],
        case_id=state["case_id"],
        user_id=state["user_id"],
        workflow_definition=state["workflow_definition"],
        max_parallel_steps=state.get("max_parallel_steps", 3),
        require_plan_approval=False,  # План уже одобрен
        auto_adapt=state.get("auto_adapt", True)
    )
    
    orchestrator = WorkflowOrchestratorAgent(config, db, rag_service)
    orchestrator.results = step_results  # Передаём предыдущие результаты
    
    import asyncio
    
    async def execute_steps():
        results = {}
        errors = []
        
        for step_data in steps:
            if step_data.get("status") == "skipped":
                continue
            
            step = WorkflowStep(
                id=step_data["id"],
                name=step_data["name"],
                description=step_data.get("description", ""),
                step_type=step_data.get("type", "custom"),
                dependencies=step_data.get("dependencies", []),
                config=step_data.get("config", {})
            )
            
            try:
                result = await orchestrator.execute_step(step)
                results[step.id] = result
            except Exception as e:
                errors.append({"step_id": step.id, "error": str(e)})
        
        return results, errors
    
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, execute_steps())
                results, errors = future.result(timeout=300)
        else:
            results, errors = loop.run_until_complete(execute_steps())
    except RuntimeError:
        results, errors = asyncio.run(execute_steps())
    
    step_results.update(results)
    step_errors.extend(errors)
    
    new_state["step_results"] = step_results
    new_state["step_errors"] = step_errors
    new_state["current_level"] = current_level + 1
    
    completed_count = len(results)
    error_count = len(errors)
    
    new_state["messages"] = [AIMessage(
        content=f"📍 Уровень {current_level}: {completed_count} выполнено, {error_count} ошибок"
    )]
    
    logger.info(f"[WorkflowGraph] Level {current_level} complete: {completed_count} steps, {error_count} errors")
    return new_state


def collect_level_results_node(state: WorkflowGraphState) -> WorkflowGraphState:
    """
    Узел сбора результатов уровня после параллельного выполнения.
    
    Агрегирует результаты от всех Send и обновляет current_level.
    """
    logger.info("[WorkflowGraph] Collecting level results")
    
    new_state = dict(state)
    
    # Результаты уже агрегированы через reducers
    step_results = state.get("step_results", {})
    step_errors = state.get("step_errors", [])
    current_level = state.get("current_level", 0)
    
    # Увеличиваем уровень
    new_state["current_level"] = current_level + 1
    
    completed_count = len(step_results)
    error_count = len(step_errors)
    
    new_state["messages"] = [AIMessage(
        content=f"📍 Уровень {current_level}: {completed_count} выполнено, {error_count} ошибок"
    )]
    
    logger.info(f"[WorkflowGraph] Level {current_level} results collected: {completed_count} steps, {error_count} errors")
    return new_state


def monitor_node(state: WorkflowGraphState) -> WorkflowGraphState:
    """
    Узел мониторинга выполнения.
    """
    logger.info("[WorkflowGraph] Monitoring execution")
    
    new_state = dict(state)
    new_state["current_phase"] = "monitor"
    
    step_results = state.get("step_results", {})
    step_errors = state.get("step_errors", [])
    plan = state.get("plan", {})
    
    total_steps = plan.get("total_steps", 0)
    completed_steps = len(step_results)
    failed_steps = len(step_errors)
    
    stats = {
        "total_steps": total_steps,
        "completed_steps": completed_steps,
        "failed_steps": failed_steps,
        "success_rate": completed_steps / total_steps if total_steps > 0 else 0,
        "analysis": state.get("execution_stats", {}).get("analysis", {})
    }
    
    new_state["execution_stats"] = stats
    
    return new_state


def synthesize_node(state: WorkflowGraphState, db: Session = None) -> WorkflowGraphState:
    """
    Узел синтеза финальных результатов.
    """
    logger.info("[WorkflowGraph] Synthesizing results")
    
    new_state = dict(state)
    new_state["current_phase"] = "synthesize"
    
    step_results = state.get("step_results", {})
    step_errors = state.get("step_errors", [])
    plan = state.get("plan", {})
    stats = state.get("execution_stats", {})
    
    # Формируем финальный результат
    final_result = {
        "workflow_id": state["workflow_id"],
        "status": "completed" if not step_errors else "completed_with_errors",
        "summary": {
            "name": plan.get("name"),
            "total_steps": stats.get("total_steps", 0),
            "completed": stats.get("completed_steps", 0),
            "failed": stats.get("failed_steps", 0),
            "success_rate": stats.get("success_rate", 0)
        },
        "results": step_results,
        "errors": step_errors if step_errors else None
    }
    
    new_state["final_result"] = final_result
    
    status_emoji = "✅" if not step_errors else "⚠️"
    new_state["messages"] = [AIMessage(
        content=f"{status_emoji} Workflow завершён: {stats.get('completed_steps', 0)}/{stats.get('total_steps', 0)} шагов выполнено"
    )]
    
    # Сохраняем результат в БД если нужно
    if db:
        try:
            from app.services.workflows.workflow_service import WorkflowService
            service = WorkflowService(db)
            service.update_workflow_execution(
                workflow_id=state["workflow_id"],
                status="completed" if not step_errors else "completed_with_errors",
                result=final_result
            )
        except Exception as e:
            logger.warning(f"[WorkflowGraph] Failed to save result to DB: {e}")
    
    logger.info(f"[WorkflowGraph] Synthesis complete: {final_result['status']}")
    return new_state


# ============== Routing Functions ==============

def route_after_plan(state: WorkflowGraphState) -> str:
    """Определить следующий узел после генерации плана."""
    if state.get("require_approval", True):
        return "approval_interrupt"
    else:
        return "execute_level"


def route_after_approval(state: WorkflowGraphState) -> str:
    """Определить следующий узел после одобрения."""
    if state.get("plan_approved", False):
        return "execute_level"
    else:
        return "end_node"


def route_after_execute(state: WorkflowGraphState) -> str:
    """Определить следующий узел после выполнения уровня."""
    current_level = state.get("current_level", 0)
    plan = state.get("plan", {})
    levels = plan.get("levels", [])
    
    if current_level < len(levels):
        return "execute_level"  # Продолжаем выполнение
    else:
        return "monitor"  # Все уровни выполнены


# ============== End Node ==============

def end_node(state: WorkflowGraphState) -> WorkflowGraphState:
    """Финальный узел."""
    new_state = dict(state)
    new_state["current_phase"] = "end"
    return new_state


# ============== Graph Builder ==============

def create_workflow_graph(
    db: Session = None,
    rag_service: RAGService = None,
    use_checkpointing: bool = True,
    use_send_api: bool = True,
    interrupt_before: List[str] = None,
    interrupt_after: List[str] = None
):
    """
    Создать LangGraph граф для Workflows.
    
    Args:
        db: Database session
        rag_service: RAG service
        use_checkpointing: Использовать checkpointing (важно для HITL)
        use_send_api: Использовать Send API для параллельного выполнения шагов
        interrupt_before: Узлы для прерывания перед выполнением
        interrupt_after: Узлы для прерывания после выполнения
    
    Returns:
        Compiled LangGraph
    
    # АРХИТЕКТУРА ГРАФА (с Send API)
    ```
    START
      ↓
    analyze
      ↓
    generate_plan
      ↓
      ├── require_approval=True → approval_interrupt → apply_approval
      │                                                    ↓
      └── require_approval=False ──────────────────────────┘
                                                           ↓
                                                 dispatch_parallel_steps
                                                           ↓
                                                 [Send] execute_single_step (параллельно)
                                                           ↓
                                                 collect_level_results
                                                           ↓
                                                 (loop или monitor)
                                                           ↓
                                                       synthesize
                                                           ↓
                                                          END
    ```
    """
    logger.info(f"[WorkflowGraph] Creating workflow graph (use_send_api={use_send_api})")
    
    # Создаём граф
    graph = StateGraph(WorkflowGraphState)
    
    # Wrapper функции с db и rag_service
    def analyze_wrapper(state):
        return analyze_node(state, db)
    
    def generate_plan_wrapper(state):
        return generate_plan_node(state, db)
    
    def execute_level_wrapper(state):
        return execute_level_node(state, db, rag_service)
    
    def execute_single_step_wrapper(state):
        return execute_single_step_node(state, db, rag_service)
    
    def synthesize_wrapper(state):
        return synthesize_node(state, db)
    
    # Добавляем узлы
    graph.add_node("analyze", analyze_wrapper)
    graph.add_node("generate_plan", generate_plan_wrapper)
    graph.add_node("approval_interrupt", approval_interrupt_node)
    graph.add_node("apply_approval", apply_approval_node)
    
    if use_send_api:
        # Send API: параллельное выполнение шагов
        graph.add_node("dispatch_parallel_steps", dispatch_parallel_steps_node)
        graph.add_node("execute_single_step", execute_single_step_wrapper)
        graph.add_node("collect_level_results", collect_level_results_node)
    else:
        # Fallback: последовательное выполнение
        graph.add_node("execute_level", execute_level_wrapper)
    
    graph.add_node("monitor", monitor_node)
    graph.add_node("synthesize", synthesize_wrapper)
    graph.add_node("end_node", end_node)
    
    # Добавляем рёбра
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "generate_plan")
    
    # Routing function для выбора между Send API и fallback
    def route_after_plan_wrapper(state):
        if state.get("require_approval", True):
            return "approval_interrupt"
        else:
            return "dispatch_parallel_steps" if use_send_api else "execute_level"
    
    def route_after_approval_wrapper(state):
        if state.get("plan_approved", False):
            return "dispatch_parallel_steps" if use_send_api else "execute_level"
        else:
            return "end_node"
    
    if use_send_api:
        # Send API routing
        graph.add_conditional_edges(
            "generate_plan",
            route_after_plan_wrapper,
            {
                "approval_interrupt": "approval_interrupt",
                "dispatch_parallel_steps": "dispatch_parallel_steps"
            }
        )
        
        graph.add_edge("approval_interrupt", "apply_approval")
        
        graph.add_conditional_edges(
            "apply_approval",
            route_after_approval_wrapper,
            {
                "dispatch_parallel_steps": "dispatch_parallel_steps",
                "end_node": "end_node"
            }
        )
        
        # dispatch_parallel_steps возвращает List[Send]
        # execute_single_step результаты собираются через reducer
        graph.add_edge("execute_single_step", "collect_level_results")
        
        # После сбора результатов - проверяем, есть ли ещё уровни
        def route_after_collect(state):
            current_level = state.get("current_level", 0)
            plan = state.get("plan", {})
            levels = plan.get("levels", [])
            
            if current_level < len(levels):
                return "dispatch_parallel_steps"  # Следующий уровень
            else:
                return "monitor"  # Все уровни выполнены
        
        graph.add_conditional_edges(
            "collect_level_results",
            route_after_collect,
            {
                "dispatch_parallel_steps": "dispatch_parallel_steps",
                "monitor": "monitor"
            }
        )
    else:
        # Fallback routing (последовательное выполнение)
        graph.add_conditional_edges(
            "generate_plan",
            route_after_plan_wrapper,
            {
                "approval_interrupt": "approval_interrupt",
                "execute_level": "execute_level"
            }
        )
        
        graph.add_edge("approval_interrupt", "apply_approval")
        
        graph.add_conditional_edges(
            "apply_approval",
            route_after_approval_wrapper,
            {
                "execute_level": "execute_level",
                "end_node": "end_node"
            }
        )
        
        graph.add_conditional_edges(
            "execute_level",
            route_after_execute,
            {
                "execute_level": "execute_level",
                "monitor": "monitor"
            }
        )
    
    # Финальные рёбра
    graph.add_edge("monitor", "synthesize")
    graph.add_edge("synthesize", "end_node")
    graph.add_edge("end_node", END)
    
    # Compile kwargs с input/output schemas и breakpoints
    compile_kwargs = {
        "input": WorkflowGraphInputState,
        "output": WorkflowGraphOutputState,
    }
    
    # Добавляем breakpoints если указаны
    if interrupt_before:
        compile_kwargs["interrupt_before"] = interrupt_before
        logger.info(f"[WorkflowGraph] interrupt_before: {interrupt_before}")
    if interrupt_after:
        compile_kwargs["interrupt_after"] = interrupt_after
        logger.info(f"[WorkflowGraph] interrupt_after: {interrupt_after}")
    
    # Получаем Store для долгосрочной памяти
    store = get_store_instance()
    if store:
        compile_kwargs["store"] = store
        logger.info("[WorkflowGraph] Store integrated for long-term memory")
    
    if use_checkpointing:
        try:
            checkpointer = get_checkpointer_instance()
            compiled = graph.compile(checkpointer=checkpointer, **compile_kwargs)
            logger.info("[WorkflowGraph] Compiled with PostgresSaver checkpointer, Store and input/output schemas")
        except Exception as e:
            logger.warning(f"[WorkflowGraph] Failed to get PostgresSaver, using MemorySaver: {e}")
            compiled = graph.compile(checkpointer=MemorySaver(), **compile_kwargs)
    else:
        compiled = graph.compile(checkpointer=MemorySaver(), **compile_kwargs)
    
    logger.info("[WorkflowGraph] Graph created successfully")
    return compiled



