"""
TabularGraph - LangGraph граф для страницы Tabular Review.

# РОЛЬ
Граф для извлечения структурированных данных из документов в табличную форму
с поддержкой Human-in-the-Loop для ячеек с низкой уверенностью.

# ПАТТЕРН: Map-Reduce
- Map: Параллельное извлечение данных из каждого документа
- Reduce: Объединение и валидация результатов
- HITL: Запрос уточнений для ячеек с confidence < threshold

# АРХИТЕКТУРА ГРАФА
```
START
  ↓
validate (проверка колонок и файлов)
  ↓
map_extract (параллельное извлечение)
  ↓
reduce_merge (объединение результатов)
  ↓
check_confidence (проверка уверенности)
  ↓
  ├── confidence >= threshold → save → END
  │
  └── confidence < threshold → clarify_interrupt (HITL)
                                    ↓
                               [user response]
                                    ↓
                                  save → END
```

# КОГДА ИСПОЛЬЗОВАТЬ
- Извлечение данных из множества документов в таблицу
- Нужна оценка уверенности для каждой ячейки
- Важен контроль качества через HITL

# КОГДА НЕ ИСПОЛЬЗОВАТЬ
- Простой поиск информации → используй ChatGraph
- Один документ, один вопрос → используй rag_search
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
    append_unique_reducer,
    sort_by_confidence_reducer,
    append_errors_reducer,
)
from app.services.langchain_agents.graphs.subgraphs.file_extraction import (
    create_file_extraction_subgraph,
    FileExtractionState,
    create_initial_file_extraction_state,
)
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


# ============== State Definition ==============

# Input Schema - только входные данные
class TabularGraphInputState(TypedDict):
    """
    Входное состояние графа Tabular Review.
    
    Содержит только данные, необходимые для начала обработки.
    """
    review_id: str
    case_id: str
    user_id: str
    columns: List[Dict[str, Any]]
    file_ids: List[str]
    confidence_threshold: float
    enable_hitl: bool


# Output Schema - только результаты
class TabularGraphOutputState(TypedDict):
    """
    Выходное состояние графа Tabular Review.
    
    Содержит только финальные результаты.
    """
    saved_count: Optional[int]
    merged_results: Optional[List[Dict[str, Any]]]
    errors: Optional[List[str]]
    current_phase: str


# Full State - полное внутреннее состояние
class TabularGraphState(TypedDict):
    """
    Состояние графа Tabular Review.
    
    Использует кастомные редьюсеры для:
    - messages: стандартный operator.add для конкатенации
    - extraction_results: append_unique_reducer для объединения без дубликатов
    - merged_results: sort_by_confidence_reducer для сортировки по уверенности
    - errors: append_errors_reducer для накопления ошибок
    """
    # Входные данные
    review_id: str
    case_id: str
    user_id: str
    
    # Конфигурация колонок
    columns: List[Dict[str, Any]]  # [{id, label, column_type, prompt, config}]
    file_ids: List[str]
    
    # Опции
    confidence_threshold: float
    enable_hitl: bool
    
    # Промежуточные результаты
    validation_result: Optional[Dict[str, Any]]
    extraction_results: Annotated[Optional[List[Dict[str, Any]]], append_unique_reducer]  # Результаты Map
    merged_results: Annotated[Optional[List[Dict[str, Any]]], sort_by_confidence_reducer]  # Результаты Reduce
    
    # HITL
    clarification_requests: Optional[List[Dict[str, Any]]]
    clarification_responses: Optional[Dict[str, Any]]  # {request_id: {value, confirmed}}
    
    # Результат
    saved_count: Optional[int]
    errors: Annotated[Optional[List[str]], append_errors_reducer]
    
    # Метаданные
    messages: Annotated[List[BaseMessage], add_messages]  # add_messages поддерживает RemoveMessage и перезапись по ID
    current_phase: str


def create_initial_tabular_state(
    review_id: str,
    case_id: str,
    user_id: str,
    columns: List[Dict[str, Any]],
    file_ids: List[str],
    confidence_threshold: float = 0.8,
    enable_hitl: bool = True
) -> TabularGraphState:
    """Создать начальное состояние для графа Tabular Review."""
    return TabularGraphState(
        review_id=review_id,
        case_id=case_id,
        user_id=user_id,
        columns=columns,
        file_ids=file_ids,
        confidence_threshold=confidence_threshold,
        enable_hitl=enable_hitl,
        validation_result=None,
        extraction_results=None,
        merged_results=None,
        clarification_requests=None,
        clarification_responses=None,
        saved_count=None,
        errors=None,
        messages=[HumanMessage(content=f"Начинаю извлечение данных для {len(file_ids)} документов по {len(columns)} колонкам")],
        current_phase="init"
    )


# ============== Node Functions ==============

def validate_node(state: TabularGraphState, db: Session = None) -> TabularGraphState:
    """
    Узел валидации входных данных.
    
    Проверяет:
    - Наличие колонок и файлов
    - Корректность типов колонок
    - Доступность файлов
    """
    logger.info(f"[TabularGraph] Validating input for review {state['review_id']}")
    
    new_state = dict(state)
    new_state["current_phase"] = "validate"
    
    errors = []
    
    # Проверяем колонки
    columns = state.get("columns", [])
    if not columns:
        errors.append("Не указаны колонки для извлечения")
    else:
        valid_types = ["text", "number", "currency", "yes_no", "date", "tag", "verbatim"]
        for col in columns:
            if not col.get("id"):
                errors.append(f"Колонка без ID: {col}")
            if col.get("column_type") not in valid_types:
                errors.append(f"Неизвестный тип колонки: {col.get('column_type')}")
    
    # Проверяем файлы
    file_ids = state.get("file_ids", [])
    if not file_ids:
        errors.append("Не указаны файлы для обработки")
    elif db:
        from app.models.case import File
        existing_files = db.query(File.id).filter(File.id.in_(file_ids)).all()
        existing_ids = {str(f.id) for f in existing_files}
        missing = set(file_ids) - existing_ids
        if missing:
            errors.append(f"Файлы не найдены: {missing}")
    
    new_state["validation_result"] = {
        "valid": len(errors) == 0,
        "columns_count": len(columns),
        "files_count": len(file_ids),
        "errors": errors
    }
    new_state["errors"] = errors if errors else None
    
    if errors:
        new_state["messages"] = [AIMessage(content=f"❌ Ошибка валидации: {'; '.join(errors)}")]
    else:
        new_state["messages"] = [AIMessage(content=f"✅ Валидация пройдена: {len(columns)} колонок, {len(file_ids)} файлов")]
    
    logger.info(f"[TabularGraph] Validation result: valid={len(errors) == 0}, errors={errors}")
    return new_state


def map_dispatch_node(state: TabularGraphState) -> List[Send]:
    """
    Узел диспетчеризации Map - создаёт Send для каждого файла.
    
    Использует Send API для параллельной обработки файлов.
    Каждый файл обрабатывается независимо в extract_single_file узле.
    """
    file_ids = state.get("file_ids", [])
    
    logger.info(f"[TabularGraph] Dispatching extraction for {len(file_ids)} files via Send API")
    
    # Создаём Send для каждого файла
    sends = []
    for file_id in file_ids:
        sends.append(
            Send(
                "extract_single_file",
                {
                    "file_id": file_id,
                    "case_id": state["case_id"],
                    "user_id": state["user_id"],
                    "columns": state["columns"],
                    "confidence_threshold": state.get("confidence_threshold", 0.8),
                }
            )
        )
    
    return sends


def extract_single_file_node(state: Dict[str, Any], db: Session = None) -> Dict[str, Any]:
    """
    Узел извлечения из одного файла.
    
    Вызывается параллельно для каждого файла через Send API.
    Использует sub-graph для изоляции.
    """
    file_id = state.get("file_id")
    logger.info(f"[TabularGraph] Extracting from file {file_id}")
    
    try:
        # Создаём sub-graph
        subgraph = create_file_extraction_subgraph(db)
        
        # Создаём состояние для sub-graph
        subgraph_state = create_initial_file_extraction_state(
            file_id=file_id,
            case_id=state["case_id"],
            user_id=state["user_id"],
            columns=state["columns"],
            confidence_threshold=state.get("confidence_threshold", 0.8)
        )
        
        # Выполняем sub-graph
        result = subgraph.invoke(subgraph_state)
        
        # Возвращаем результаты для reducer
        return {
            "extraction_results": result.get("extraction_results", []),
            "clarification_requests": result.get("clarification_requests", []),
            "errors": result.get("errors"),
            "current_phase": "map_extract"
        }
        
    except Exception as e:
        logger.error(f"[TabularGraph] File extraction error: {e}", exc_info=True)
        return {
            "extraction_results": [],
            "clarification_requests": [],
            "errors": [f"File {file_id} extraction error: {str(e)}"],
            "current_phase": "map_extract"
        }


def map_extract_node(state: TabularGraphState, db: Session = None) -> TabularGraphState:
    """
    Узел Map - параллельное извлечение из документов.
    
    Для каждого документа извлекает значения всех колонок.
    
    ПРИМЕЧАНИЕ: Этот узел используется как fallback когда Send API недоступен.
    Предпочтительно использовать map_dispatch_node + extract_single_file_node.
    """
    logger.info(f"[TabularGraph] Starting Map extraction for {len(state['file_ids'])} files (legacy mode)")
    
    new_state = dict(state)
    new_state["current_phase"] = "map_extract"
    
    from app.services.langchain_agents.agents.tabular_extraction_agent import (
        TabularExtractionAgent,
        TabularExtractionConfig,
        ExtractionColumn
    )
    
    try:
        # Преобразуем колонки
        columns = [
            ExtractionColumn(
                id=col["id"],
                label=col.get("label", col["id"]),
                column_type=col.get("column_type", "text"),
                prompt=col.get("prompt", f"Извлеки {col.get('label', col['id'])}"),
                config=col.get("config")
            )
            for col in state["columns"]
        ]
        
        # Создаём конфигурацию
        config = TabularExtractionConfig(
            review_id=state["review_id"],
            case_id=state["case_id"],
            user_id=state["user_id"],
            columns=columns,
            file_ids=state["file_ids"],
            confidence_threshold=state.get("confidence_threshold", 0.8),
            enable_hitl=state.get("enable_hitl", True)
        )
        
        # Создаём агента и запускаем извлечение
        agent = TabularExtractionAgent(config, db)
        
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, agent.extract_all())
                    result = future.result(timeout=300)  # 5 минут timeout
            else:
                result = loop.run_until_complete(agent.extract_all())
        except RuntimeError:
            result = asyncio.run(agent.extract_all())
        
        new_state["extraction_results"] = result.get("successful", [])
        new_state["clarification_requests"] = result.get("needs_clarification", [])
        
        success_count = len(result.get("successful", []))
        clarify_count = len(result.get("needs_clarification", []))
        
        new_state["messages"] = [AIMessage(
            content=f"📊 Извлечено {success_count} значений, {clarify_count} требуют уточнения"
        )]
        
        logger.info(f"[TabularGraph] Map extraction complete: {success_count} successful, {clarify_count} need clarification")
        
    except Exception as e:
        logger.error(f"[TabularGraph] Map extraction error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Extraction error: {str(e)}"]
        new_state["extraction_results"] = []
        new_state["messages"] = [AIMessage(content=f"❌ Ошибка извлечения: {str(e)}")]
    
    return new_state


def reduce_merge_node(state: TabularGraphState) -> TabularGraphState:
    """
    Узел Reduce - объединение результатов.
    
    Объединяет результаты Map в единую структуру.
    """
    logger.info("[TabularGraph] Starting Reduce merge")
    
    new_state = dict(state)
    new_state["current_phase"] = "reduce_merge"
    
    extraction_results = state.get("extraction_results", [])
    clarification_requests = state.get("clarification_requests", [])
    
    # Группируем по file_id для удобства
    results_by_file = {}
    for result in extraction_results:
        file_id = result.get("file_id")
        if file_id not in results_by_file:
            results_by_file[file_id] = []
        results_by_file[file_id].append(result)
    
    # Добавляем clarification_requests
    for request in clarification_requests:
        file_id = request.get("file_id")
        if file_id not in results_by_file:
            results_by_file[file_id] = []
        results_by_file[file_id].append(request)
    
    new_state["merged_results"] = extraction_results
    
    # Статистика
    total_cells = len(extraction_results) + len(clarification_requests)
    high_confidence = sum(1 for r in extraction_results if r.get("confidence", 0) >= 0.8)
    
    new_state["messages"] = [AIMessage(
        content=f"🔄 Объединено {total_cells} ячеек, {high_confidence} с высокой уверенностью"
    )]
    
    logger.info(f"[TabularGraph] Reduce merge complete: {total_cells} total cells")
    return new_state


def check_confidence_node(state: TabularGraphState) -> TabularGraphState:
    """
    Узел проверки уверенности.
    
    Определяет, нужен ли HITL.
    """
    logger.info("[TabularGraph] Checking confidence levels")
    
    new_state = dict(state)
    new_state["current_phase"] = "check_confidence"
    
    clarification_requests = state.get("clarification_requests", [])
    enable_hitl = state.get("enable_hitl", True)
    
    if clarification_requests and enable_hitl:
        new_state["messages"] = [AIMessage(
            content=f"⚠️ {len(clarification_requests)} ячеек требуют уточнения"
        )]
    else:
        new_state["messages"] = [AIMessage(content="✅ Все значения извлечены с достаточной уверенностью")]
    
    return new_state


def clarify_interrupt_node(state: TabularGraphState) -> TabularGraphState:
    """
    Узел HITL через interrupt.
    
    Прерывает выполнение и запрашивает уточнение у пользователя.
    """
    from langgraph.types import interrupt
    
    logger.info("[TabularGraph] Requesting clarification via interrupt")
    
    new_state = dict(state)
    new_state["current_phase"] = "clarify"
    
    clarification_requests = state.get("clarification_requests", [])
    
    if clarification_requests:
        # Формируем payload для interrupt
        interrupt_payload = {
            "type": "table_clarification",
            "review_id": state["review_id"],
            "requests": [
                {
                    "request_id": f"{r.get('file_id')}_{r.get('column_id')}",
                    "column_id": r.get("column_id"),
                    "file_id": r.get("file_id"),
                    "question": r.get("clarification_question"),
                    "current_value": r.get("value"),
                    "confidence": r.get("confidence")
                }
                for r in clarification_requests
            ]
        }
        
        # Вызываем interrupt - граф остановится здесь
        # и возобновится после Command(resume=...)
        interrupt(interrupt_payload)
    
    return new_state


def apply_clarifications_node(state: TabularGraphState) -> TabularGraphState:
    """
    Узел применения уточнений от пользователя.
    
    Вызывается после resume с ответами пользователя.
    """
    logger.info("[TabularGraph] Applying user clarifications")
    
    new_state = dict(state)
    new_state["current_phase"] = "apply_clarifications"
    
    clarification_responses = state.get("clarification_responses", {})
    clarification_requests = state.get("clarification_requests", [])
    merged_results = list(state.get("merged_results", []))
    
    applied_count = 0
    
    for request in clarification_requests:
        request_id = f"{request.get('file_id')}_{request.get('column_id')}"
        response = clarification_responses.get(request_id)
        
        if response:
            # Применяем ответ пользователя
            merged_results.append({
                "column_id": request.get("column_id"),
                "file_id": request.get("file_id"),
                "value": response.get("value", ""),
                "confidence": 1.0 if response.get("confirmed", False) else 0.0,
                "source_quote": None,
                "source_page": None,
                "needs_clarification": False
            })
            applied_count += 1
    
    new_state["merged_results"] = merged_results
    new_state["clarification_requests"] = []  # Очищаем запросы
    new_state["messages"] = [AIMessage(content=f"✅ Применено {applied_count} уточнений")]
    
    logger.info(f"[TabularGraph] Applied {applied_count} clarifications")
    return new_state


def save_results_node(state: TabularGraphState, db: Session = None) -> TabularGraphState:
    """
    Узел сохранения результатов.
    
    Сохраняет извлечённые данные в базу.
    """
    logger.info(f"[TabularGraph] Saving results for review {state['review_id']}")
    
    new_state = dict(state)
    new_state["current_phase"] = "save"
    
    merged_results = state.get("merged_results", [])
    
    if not db:
        logger.warning("[TabularGraph] No database session, skipping save")
        new_state["saved_count"] = 0
        new_state["messages"] = [AIMessage(content="⚠️ Результаты не сохранены (нет подключения к БД)")]
        return new_state
    
    try:
        from app.services.tabular_review_service import TabularReviewService
        
        service = TabularReviewService(db)
        saved_count = 0
        errors = []
        
        for result in merged_results:
            try:
                service.update_cell(
                    review_id=state["review_id"],
                    file_id=result["file_id"],
                    column_id=result["column_id"],
                    value=result.get("value", ""),
                    user_id=state["user_id"],
                    is_manual=False,
                    confidence=result.get("confidence"),
                    source_quote=result.get("source_quote")
                )
                saved_count += 1
            except Exception as e:
                errors.append(f"Cell {result['file_id']}/{result['column_id']}: {str(e)}")
        
        new_state["saved_count"] = saved_count
        new_state["errors"] = errors if errors else None
        
        if errors:
            new_state["messages"] = [AIMessage(
                content=f"⚠️ Сохранено {saved_count} ячеек, {len(errors)} ошибок"
            )]
        else:
            new_state["messages"] = [AIMessage(content=f"✅ Сохранено {saved_count} ячеек")]
        
        logger.info(f"[TabularGraph] Saved {saved_count} cells, {len(errors)} errors")
        
    except Exception as e:
        logger.error(f"[TabularGraph] Save error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Save error: {str(e)}"]
        new_state["saved_count"] = 0
        new_state["messages"] = [AIMessage(content=f"❌ Ошибка сохранения: {str(e)}")]
    
    return new_state


# ============== Routing Functions ==============

def route_after_validation(state: TabularGraphState, use_send_api: bool = True) -> str:
    """Определить следующий узел после валидации."""
    validation = state.get("validation_result", {})
    if validation.get("valid", False):
        return "map_dispatch" if use_send_api else "map_extract"
    else:
        return "end_node"


def route_after_confidence(state: TabularGraphState) -> str:
    """Определить следующий узел после проверки уверенности."""
    clarification_requests = state.get("clarification_requests", [])
    enable_hitl = state.get("enable_hitl", True)
    
    if clarification_requests and enable_hitl:
        return "clarify_interrupt"
    else:
        return "save_results"


def route_after_clarify(state: TabularGraphState) -> str:
    """Определить следующий узел после interrupt."""
    # После resume всегда идём в apply_clarifications
    return "apply_clarifications"


# ============== End Node ==============

def end_node(state: TabularGraphState) -> TabularGraphState:
    """Финальный узел."""
    new_state = dict(state)
    new_state["current_phase"] = "complete"
    return new_state


# ============== Graph Builder ==============

def create_tabular_graph(
    db: Session = None,
    use_checkpointing: bool = True,
    interrupt_before: List[str] = None,
    interrupt_after: List[str] = None,
    use_send_api: bool = True
):
    """
    Создать LangGraph граф для Tabular Review.
    
    Args:
        db: Database session
        use_checkpointing: Использовать checkpointing (важно для HITL)
        interrupt_before: Узлы для прерывания перед выполнением
        interrupt_after: Узлы для прерывания после выполнения
        use_send_api: Использовать Send API для параллельной обработки файлов
    
    Returns:
        Compiled LangGraph
    
    # АРХИТЕКТУРА ГРАФА (с Send API)
    ```
    START
      ↓
    validate (проверка колонок и файлов)
      ↓
    map_dispatch ──→ [Send] extract_single_file (параллельно для каждого файла)
      ↓                      ↓
    reduce_merge ←──────────┘ (собирает результаты)
      ↓
    check_confidence (проверка уверенности)
      ↓
      ├── confidence >= threshold → save → END
      │
      └── confidence < threshold → clarify_interrupt (HITL)
                                        ↓
                                   [user response]
                                        ↓
                                      save → END
    ```
    """
    logger.info(f"[TabularGraph] Creating tabular graph (use_send_api={use_send_api})")
    
    # Создаём граф
    graph = StateGraph(TabularGraphState)
    
    # Wrapper функции с db
    def validate_wrapper(state):
        return validate_node(state, db)
    
    def map_extract_wrapper(state):
        return map_extract_node(state, db)
    
    def extract_single_file_wrapper(state):
        return extract_single_file_node(state, db)
    
    def save_results_wrapper(state):
        return save_results_node(state, db)
    
    # Добавляем узлы
    graph.add_node("validate", validate_wrapper)
    
    if use_send_api:
        # Используем Send API для параллельной обработки
        graph.add_node("map_dispatch", map_dispatch_node)
        graph.add_node("extract_single_file", extract_single_file_wrapper)
    else:
        # Fallback: последовательная обработка
        graph.add_node("map_extract", map_extract_wrapper)
    
    graph.add_node("reduce_merge", reduce_merge_node)
    graph.add_node("check_confidence", check_confidence_node)
    graph.add_node("clarify_interrupt", clarify_interrupt_node)
    graph.add_node("apply_clarifications", apply_clarifications_node)
    graph.add_node("save_results", save_results_wrapper)
    graph.add_node("end_node", end_node)
    
    # Добавляем рёбра
    graph.add_edge(START, "validate")
    
    # После валидации - создаём routing function с учётом use_send_api
    def route_after_validation_wrapper(state):
        validation = state.get("validation_result", {})
        if validation.get("valid", False):
            return "map_dispatch" if use_send_api else "map_extract"
        else:
            return "end_node"
    
    if use_send_api:
        # Send API: validate -> map_dispatch -> [Send] extract_single_file -> reduce_merge
        graph.add_conditional_edges(
            "validate",
            route_after_validation_wrapper,
            {
                "map_dispatch": "map_dispatch",
                "end_node": "end_node"
            }
        )
        # map_dispatch возвращает List[Send], которые параллельно вызывают extract_single_file
        # extract_single_file результаты собираются через reducer и передаются в reduce_merge
        graph.add_edge("extract_single_file", "reduce_merge")
    else:
        # Legacy: validate -> map_extract -> reduce_merge
        graph.add_conditional_edges(
            "validate",
            route_after_validation_wrapper,
            {
                "map_extract": "map_extract",
                "end_node": "end_node"
            }
        )
        graph.add_edge("map_extract", "reduce_merge")
    
    graph.add_edge("reduce_merge", "check_confidence")
    
    # После проверки уверенности
    graph.add_conditional_edges(
        "check_confidence",
        route_after_confidence,
        {
            "clarify_interrupt": "clarify_interrupt",
            "save_results": "save_results"
        }
    )
    
    # После interrupt (resume) -> apply_clarifications
    graph.add_edge("clarify_interrupt", "apply_clarifications")
    graph.add_edge("apply_clarifications", "save_results")
    
    # Финальные рёбра
    graph.add_edge("save_results", "end_node")
    graph.add_edge("end_node", END)
    
    # Компилируем граф с input/output schemas и breakpoints
    # ВАЖНО: для HITL через interrupt нужен checkpointer
    compile_kwargs = {
        "input": TabularGraphInputState,
        "output": TabularGraphOutputState,
    }
    
    # Добавляем breakpoints если указаны
    if interrupt_before:
        compile_kwargs["interrupt_before"] = interrupt_before
        logger.info(f"[TabularGraph] interrupt_before: {interrupt_before}")
    if interrupt_after:
        compile_kwargs["interrupt_after"] = interrupt_after
        logger.info(f"[TabularGraph] interrupt_after: {interrupt_after}")
    
    # Получаем Store для долгосрочной памяти
    store = get_store_instance()
    if store:
        compile_kwargs["store"] = store
        logger.info("[TabularGraph] Store integrated for long-term memory")
    
    if use_checkpointing:
        try:
            checkpointer = get_checkpointer_instance()
            compiled = graph.compile(checkpointer=checkpointer, **compile_kwargs)
            logger.info("[TabularGraph] Compiled with PostgresSaver checkpointer, Store and input/output schemas")
        except Exception as e:
            logger.warning(f"[TabularGraph] Failed to get PostgresSaver, using MemorySaver: {e}")
            compiled = graph.compile(checkpointer=MemorySaver(), **compile_kwargs)
    else:
        compiled = graph.compile(checkpointer=MemorySaver(), **compile_kwargs)  # HITL требует checkpointer
    
    logger.info("[TabularGraph] Graph created successfully")
    return compiled



