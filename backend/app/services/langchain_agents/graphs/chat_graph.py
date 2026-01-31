"""
ChatGraph - LangGraph граф для страницы чата.

# РОЛЬ
Основной граф для обработки запросов пользователя на странице AssistantChatPage.
Маршрутизирует запросы по режимам и координирует работу узлов.

# РЕЖИМЫ РАБОТЫ
- normal: RAG поиск в документах + опционально ГАРАНТ + ответ
- deep_think: RAG + ГАРАНТ + пошаговое мышление + развёрнутый ответ
- garant: RAG + приоритет ГАРАНТ + ответ с цитатами из законодательства
- draft: Создание юридического документа без RAG

# АРХИТЕКТУРА ГРАФА
```
START
  ↓
mode_router (определяет режим)
  ↓
  ├── draft → draft_node → END
  │
  └── normal/deep_think/garant
        ↓
      rag_retrieval (поиск в документах дела)
        ↓
      garant_retrieval (поиск в ГАРАНТ, если включён)
        ↓
        ├── deep_think → thinking_node → generate_response → END
        │
        └── normal/garant → generate_response → END
```

# КОГДА ИСПОЛЬЗОВАТЬ
- Ответы на вопросы пользователя в чате
- Поиск информации в документах дела
- Поиск в законодательстве (ГАРАНТ)
- Глубокий анализ с пошаговым мышлением
- Создание юридических документов
"""
from typing import TypedDict, Literal, Optional, List, Dict, Any, Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.types import Send
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, RemoveMessage, trim_messages
from app.services.llm_factory import create_llm, create_legal_llm
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.utils.checkpointer_setup import get_checkpointer_instance
from app.services.langchain_agents.store_integration import get_store_instance
from app.services.langchain_agents.utils.reducers import (
    merge_citations_reducer,
    append_errors_reducer,
)
from app.services.langchain_agents.utils.message_utils import (
    filter_messages_by_count,
    should_trim_messages,
    MessageManager,
)
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


# ============== State Definition ==============

# Input Schema - только входные данные
class ChatGraphInputState(TypedDict):
    """
    Входное состояние графа чата.
    
    Содержит только данные, необходимые для начала обработки.
    Используется как input_schema при компиляции графа.
    """
    case_id: str
    user_id: str
    question: str
    mode: Literal["normal", "deep_think", "garant", "draft"]
    enable_garant: bool
    enable_citations: bool
    document_context: Optional[str]
    document_id: Optional[str]
    selected_text: Optional[str]


# Output Schema - только результаты
class ChatGraphOutputState(TypedDict):
    """
    Выходное состояние графа чата.
    
    Содержит только финальные результаты.
    Используется как output_schema при компиляции графа.
    """
    response: Optional[str]
    citations: Optional[List[Dict[str, Any]]]
    document_created: Optional[Dict[str, Any]]
    errors: Optional[List[str]]


# Full State - полное внутреннее состояние
class ChatGraphState(TypedDict):
    """
    Состояние графа чата.
    
    Использует кастомные редьюсеры для:
    - messages: стандартный operator.add для конкатенации
    - citations: merge_citations_reducer для объединения с дедупликацией
    - errors: append_errors_reducer для накопления ошибок
    """
    # Входные данные
    case_id: str
    user_id: str
    question: str
    mode: Literal["normal", "deep_think", "garant", "draft"]
    
    # Опции
    enable_garant: bool
    enable_citations: bool
    
    # Контекст документа (для режима редактора)
    document_context: Optional[str]
    document_id: Optional[str]
    selected_text: Optional[str]
    
    # Промежуточные результаты
    rag_context: Optional[str]
    garant_context: Optional[str]
    thinking_steps: Optional[List[Dict[str, Any]]]
    
    # Memory management
    message_summary: Optional[str]  # Summary старых сообщений
    
    # Результат
    response: Optional[str]
    citations: Annotated[Optional[List[Dict[str, Any]]], merge_citations_reducer]
    document_created: Optional[Dict[str, Any]]
    
    # HITL для draft mode
    draft_plan: Optional[Dict[str, Any]]  # План документа для подтверждения
    draft_approved: bool  # Подтверждён ли план пользователем
    waiting_for_approval: bool  # Ожидает ли граф подтверждения
    
    # Метаданные
    messages: Annotated[List[BaseMessage], add_messages]  # add_messages поддерживает RemoveMessage и перезапись по ID
    errors: Annotated[Optional[List[str]], append_errors_reducer]


def create_initial_chat_state(
    case_id: str,
    user_id: str,
    question: str,
    mode: str = "normal",
    enable_garant: bool = True,
    enable_citations: bool = True,
    document_context: str = None,
    document_id: str = None,
    selected_text: str = None,
    existing_messages: List[BaseMessage] = None
) -> ChatGraphState:
    """
    Создать начальное состояние для графа чата.
    
    Args:
        case_id: ID дела
        user_id: ID пользователя
        question: Вопрос пользователя
        mode: Режим работы
        enable_garant: Включить поиск в ГАРАНТ
        enable_citations: Включить цитаты
        document_context: Контекст документа (для редактора)
        document_id: ID документа
        selected_text: Выделенный текст
        existing_messages: Существующие сообщения (для продолжения диалога)
    """
    messages = existing_messages if existing_messages else []
    messages = list(messages) + [HumanMessage(content=question)]
    
    return ChatGraphState(
        case_id=case_id,
        user_id=user_id,
        question=question,
        mode=mode,
        enable_garant=enable_garant,
        enable_citations=enable_citations,
        document_context=document_context,
        document_id=document_id,
        selected_text=selected_text,
        rag_context=None,
        garant_context=None,
        thinking_steps=None,
        message_summary=None,
        response=None,
        citations=None,
        document_created=None,
        draft_plan=None,  # HITL для draft mode
        draft_approved=False,  # HITL для draft mode
        waiting_for_approval=False,  # HITL для draft mode
        messages=messages,
        errors=None
    )


# ============== Node Functions ==============

# Константы для управления памятью
MAX_MESSAGES = 20
MAX_TOKENS = 4000
SUMMARIZE_THRESHOLD = 15
KEEP_LAST_N = 5


async def manage_memory_node(state: ChatGraphState) -> ChatGraphState:
    """
    Узел управления памятью сообщений.
    
    Проверяет длину истории сообщений и при необходимости:
    - Использует trim_messages из langchain_core для обрезки по токенам
    - Удаляет старые сообщения через RemoveMessage (работает с add_messages reducer)
    - Создаёт summary старых сообщений при необходимости
    
    Этот узел помогает избежать превышения лимитов контекста LLM
    при длинных диалогах.
    
    # ПАТТЕРН: trim_messages + RemoveMessage + add_messages
    1. Сначала пробуем trim_messages из langchain_core для обрезки по токенам
    2. Затем используем RemoveMessage для удаления старых сообщений из состояния
    3. add_messages reducer корректно обрабатывает RemoveMessage
    """
    messages = state.get("messages", [])
    
    # Проверяем нужно ли обрабатывать
    if len(messages) < SUMMARIZE_THRESHOLD and not should_trim_messages(messages, MAX_TOKENS):
        return state
    
    logger.info(f"[ManageMemory] Processing {len(messages)} messages")
    
    new_state = dict(state)
    
    try:
        # Шаг 1: Используем trim_messages из langchain_core для обрезки по токенам
        # Это встроенная функция, рекомендованная LangGraph Academy
        def simple_token_counter(msgs):
            """Простая оценка токенов: ~3 символа = 1 токен для кириллицы."""
            total = 0
            for msg in msgs:
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                total += len(content) // 3
            return total
        
        # trim_messages сохраняет SystemMessage и обрезает по токенам
        trimmed_messages = trim_messages(
            messages,
            max_tokens=MAX_TOKENS,
            token_counter=simple_token_counter,
            strategy="last",  # Оставляем последние сообщения
            allow_partial=False,
            include_system=True,  # Всегда включаем SystemMessage
            start_on="human",  # Начинаем с HumanMessage
        )
        
        # Шаг 2: Если сообщения были обрезаны, создаём RemoveMessage для удалённых
        if len(trimmed_messages) < len(messages):
            trimmed_ids = {getattr(msg, 'id', None) for msg in trimmed_messages if hasattr(msg, 'id')}
            
            # Создаём RemoveMessage для сообщений, которые не вошли в trimmed
            remove_messages = []
            for msg in messages:
                msg_id = getattr(msg, 'id', None)
                if msg_id and msg_id not in trimmed_ids:
                    remove_messages.append(RemoveMessage(id=msg_id))
            
            if remove_messages:
                # add_messages reducer обработает RemoveMessage и удалит соответствующие сообщения
                new_state["messages"] = remove_messages
                logger.info(f"[ManageMemory] trim_messages: {len(messages)} → {len(trimmed_messages)}, created {len(remove_messages)} RemoveMessage")
                return new_state
        
        # Шаг 3: Если trim_messages не помог (нет ID), используем MessageManager для summary
        if len(messages) >= SUMMARIZE_THRESHOLD:
        llm = create_legal_llm(use_rate_limiting=False)
        manager = MessageManager(
            llm=llm,
            max_messages=MAX_MESSAGES,
            max_tokens=MAX_TOKENS,
            summarize_threshold=SUMMARIZE_THRESHOLD,
            keep_last_n=KEEP_LAST_N
        )
        
        result = await manager.process_messages(messages)
        
        if result["trimmed"]:
            if result["summary"]:
                new_state["message_summary"] = result["summary"]
                    summary_msg = SystemMessage(content=f"[Краткое содержание предыдущего диалога: {result['summary']}]")
                    new_state["messages"] = [summary_msg] + result["messages"]
                else:
                    new_state["messages"] = result["messages"]
                logger.info(f"[ManageMemory] MessageManager trimmed to {len(new_state['messages'])} messages")
        
    except Exception as e:
        logger.warning(f"[ManageMemory] Error: {e}, using RemoveMessage fallback")
        # Fallback: используем RemoveMessage для простого удаления
        if len(messages) > KEEP_LAST_N:
            remove_messages = []
            for msg in messages[:-KEEP_LAST_N]:
                if hasattr(msg, 'id') and msg.id:
                    remove_messages.append(RemoveMessage(id=msg.id))
            if remove_messages:
                new_state["messages"] = remove_messages
            else:
                # Если нет ID, просто оставляем последние N сообщений
                new_state["messages"] = messages[-KEEP_LAST_N:]
    
    return new_state


def mode_router_node(state: ChatGraphState) -> ChatGraphState:
    """
    Узел маршрутизации по режиму.
    
    Определяет, какой flow использовать на основе mode.
    """
    mode = state.get("mode", "normal")
    question = state.get("question", "")
    
    logger.info(f"[ModeRouter] Routing question to mode: {mode}")
    
    # Валидация режима
    valid_modes = ["normal", "deep_think", "garant", "draft"]
    if mode not in valid_modes:
        logger.warning(f"[ModeRouter] Invalid mode '{mode}', falling back to 'normal'")
        new_state = dict(state)
        new_state["mode"] = "normal"
        return new_state
    
    return state


def rag_retrieval_node(
    state: ChatGraphState,
    rag_service: RAGService = None,
    db: Session = None
) -> ChatGraphState:
    """
    Узел получения контекста из RAG.
    
    Используется во всех режимах кроме draft.
    """
    case_id = state.get("case_id")
    question = state.get("question", "")
    
    logger.info(f"[RAGRetrieval] Retrieving context for case {case_id}")
    
    new_state = dict(state)
    
    try:
        if rag_service:
            docs = rag_service.retrieve_context(
                case_id=case_id,
                query=question,
                k=5,
                retrieval_strategy="multi_query",
                db=db
            )
            
            if docs:
                context = rag_service.format_sources_for_prompt(docs, max_context_chars=4000)
                new_state["rag_context"] = context
                
                # Сохраняем citations
                citations = []
                for i, doc in enumerate(docs, 1):
                    citations.append({
                        "index": i,
                        "source": doc.metadata.get("source", "Неизвестный источник"),
                        "page": doc.metadata.get("page"),
                        "content": doc.page_content[:200]
                    })
                new_state["citations"] = citations
                
                logger.info(f"[RAGRetrieval] Retrieved {len(docs)} documents")
            else:
                new_state["rag_context"] = ""
                logger.info("[RAGRetrieval] No documents found")
        else:
            logger.warning("[RAGRetrieval] RAG service not available")
            new_state["rag_context"] = ""
            
    except Exception as e:
        logger.error(f"[RAGRetrieval] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"RAG error: {str(e)}"]
        new_state["rag_context"] = ""
    
    return new_state


def parallel_retrieval_node(state: ChatGraphState) -> List[Send]:
    """
    Узел параллельного запуска RAG и ГАРАНТ через Send API.
    
    Использует Send API для параллельного выполнения поиска в документах дела
    и в базе ГАРАНТ, что ускоряет обработку запроса.
    
    Returns:
        List[Send] - список Send объектов для параллельного выполнения
    """
    mode = state.get("mode", "normal")
    enable_garant = state.get("enable_garant", False)
    
    sends = []
    
    # RAG всегда нужен (кроме draft mode)
    if mode != "draft":
        sends.append(Send("rag_retrieval", state))
        logger.debug("[ParallelRetrieval] Added RAG retrieval to parallel execution")
    
    # ГАРАНТ если включён
    if enable_garant and mode != "draft":
        sends.append(Send("garant_retrieval", state))
        logger.debug("[ParallelRetrieval] Added Garant retrieval to parallel execution")
    
    logger.info(f"[ParallelRetrieval] Dispatching {len(sends)} parallel retrieval tasks")
    return sends


def merge_retrieval_results_node(state: ChatGraphState) -> ChatGraphState:
    """
    Узел объединения результатов параллельного поиска.
    
    После параллельного выполнения RAG и ГАРАНТ через Send API,
    результаты уже находятся в state благодаря reducers.
    Этот узел просто проверяет наличие результатов и логирует их.
    """
    rag_context = state.get("rag_context")
    garant_context = state.get("garant_context")
    
    logger.info(f"[MergeRetrieval] RAG context: {'found' if rag_context else 'not found'}, "
                f"Garant context: {'found' if garant_context else 'not found'}")
    
    # Результаты уже в state благодаря reducers, просто возвращаем
    return state


def garant_retrieval_node(state: ChatGraphState) -> ChatGraphState:
    """
    Узел получения контекста из ГАРАНТ.
    
    Используется в режимах normal и garant.
    """
    question = state.get("question", "")
    enable_garant = state.get("enable_garant", True)
    
    new_state = dict(state)
    
    if not enable_garant:
        logger.info("[GarantRetrieval] ГАРАНТ disabled")
        new_state["garant_context"] = ""
        return new_state
    
    logger.info(f"[GarantRetrieval] Searching ГАРАНТ for: {question[:100]}...")
    
    try:
        from app.services.langchain_agents.utils import get_garant_source
        import asyncio
        
        garant_source = get_garant_source()
        if garant_source and garant_source.api_key:
            # Асинхронный вызов
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            garant_source.search(query=question, max_results=5)
                        )
                        results = future.result(timeout=30)
                else:
                    results = loop.run_until_complete(
                        garant_source.search(query=question, max_results=5)
                    )
            except RuntimeError:
                results = asyncio.run(
                    garant_source.search(query=question, max_results=5)
                )
            
            if results:
                # Форматируем результаты
                formatted_parts = []
                for i, result in enumerate(results[:5], 1):
                    title = result.title or "Без названия"
                    url = result.url or ""
                    content = result.content[:500] if result.content else ""
                    formatted_parts.append(f"[ГАРАНТ {i}] {title}\nURL: {url}\n{content}")
                
                new_state["garant_context"] = "\n\n".join(formatted_parts)
                logger.info(f"[GarantRetrieval] Found {len(results)} results")
            else:
                new_state["garant_context"] = ""
                logger.info("[GarantRetrieval] No results found")
        else:
            new_state["garant_context"] = ""
            logger.warning("[GarantRetrieval] ГАРАНТ API not available")
            
    except Exception as e:
        logger.error(f"[GarantRetrieval] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"ГАРАНТ error: {str(e)}"]
        new_state["garant_context"] = ""
    
    return new_state


def thinking_node(state: ChatGraphState) -> ChatGraphState:
    """
    Узел пошагового мышления.
    
    Используется в режиме deep_think.
    """
    question = state.get("question", "")
    rag_context = state.get("rag_context", "")
    garant_context = state.get("garant_context", "")
    
    logger.info("[Thinking] Starting deep thinking process")
    
    new_state = dict(state)
    
    try:
        from app.services.thinking_service import get_thinking_service
        import asyncio
        
        context = f"{rag_context}\n\n{garant_context}" if garant_context else rag_context
        
        thinking_service = get_thinking_service(deep_think=True)
        
        steps = []
        
        # Собираем шаги мышления
        async def collect_steps():
            async for step in thinking_service.think(
                question=question,
                context=context,
                stream_steps=True
            ):
                steps.append({
                    "phase": step.phase.value,
                    "step_number": step.step_number,
                    "total_steps": step.total_steps,
                    "content": step.content
                })
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, collect_steps())
                    future.result(timeout=60)
            else:
                loop.run_until_complete(collect_steps())
        except RuntimeError:
            asyncio.run(collect_steps())
        
        new_state["thinking_steps"] = steps
        logger.info(f"[Thinking] Completed {len(steps)} thinking steps")
        
    except Exception as e:
        logger.error(f"[Thinking] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Thinking error: {str(e)}"]
        new_state["thinking_steps"] = []
    
    return new_state


def generate_response_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Узел генерации ответа.
    
    Генерирует финальный ответ на основе контекста и режима.
    Учитывает message_summary для сохранения контекста длинных диалогов.
    
    # ПАТТЕРН: Store в config
    Store автоматически доступен через config после compile(store=...).
    Используется для получения user_profile и сохранения insights.
    
    Args:
        state: Состояние графа
        config: Конфигурация с доступом к Store через config.get("store")
        db: SQLAlchemy session
    """
    question = state.get("question", "")
    mode = state.get("mode", "normal")
    rag_context = state.get("rag_context", "")
    garant_context = state.get("garant_context", "")
    thinking_steps = state.get("thinking_steps", [])
    document_context = state.get("document_context", "")
    selected_text = state.get("selected_text", "")
    message_summary = state.get("message_summary", "")
    user_id = state.get("user_id", "")
    
    # Получаем Store из config для долгосрочной памяти
    store = config.get("store") if config else None
    user_profile = None
    
    if store and user_id:
        try:
            # Пытаемся получить профиль пользователя из Store
            # LangGraph Store API: store.get(namespace_tuple, key)
            # Namespace: ("memory", user_id), Key: "user_profile"
            if hasattr(store, 'get'):
                profile_item = store.get(("memory", user_id), "user_profile")
                if profile_item:
                    # PostgresStore возвращает объект с value атрибутом
                    user_profile = profile_item.value if hasattr(profile_item, 'value') else profile_item
                    logger.debug(f"[GenerateResponse] Loaded user profile from Store for user {user_id}")
            # Примечание: generate_response_node не async, поэтому используем только sync API
            # Если нужен async API, нужно сделать функцию async
        except Exception as e:
            logger.debug(f"[GenerateResponse] Could not load user profile: {e}")
    
    logger.info(f"[GenerateResponse] Generating response in mode: {mode}")
    
    new_state = dict(state)
    
    try:
        llm = create_legal_llm(use_rate_limiting=False)
        
        # Формируем промпт на основе режима с best practices
        system_prompts = {
            "normal": """# РОЛЬ
Ты — профессиональный юридический AI-ассистент.

# ЦЕЛЬ
Дать точный, краткий ответ на вопрос пользователя, опираясь на документы дела и законодательство.

# ИНСТРУКЦИИ
1. Используй информацию из документов дела (приоритет)
2. Дополняй информацией из ГАРАНТ (если доступна)
3. Цитируй источники в формате [1], [2], [3]
4. Отвечай кратко и по существу

# ОГРАНИЧЕНИЯ (GUARDRAILS)
- НЕ выдумывай информацию
- НЕ давай заключений без источников
- ВСЕГДА указывай источники
- Используй Markdown для форматирования""",
            
            "deep_think": """# РОЛЬ
Ты — юридический аналитик в режиме глубокого анализа.

# ЦЕЛЬ
Провести комплексный анализ вопроса с рассмотрением всех аспектов.

# СТРУКТУРА ОТВЕТА
## 📜 Правовая база
[Применимые нормы, статьи кодексов]

## 🏛️ Судебная практика
[Релевантные решения судов]

## ⚖️ Анализ позиций
[Аргументы за и против]

## ⚠️ Риски
[Возможные проблемы]

## ✅ Рекомендации
[Конкретные действия]

# ОГРАНИЧЕНИЯ (GUARDRAILS)
- Опирайся ТОЛЬКО на предоставленный контекст
- Указывай источники для каждого утверждения
- Используй Markdown для форматирования""",
            
            "garant": """# РОЛЬ
Ты — юридический консультант с доступом к базе ГАРАНТ.

# ЦЕЛЬ
Дать ответ с опорой на актуальное законодательство и судебную практику.

# ИНСТРУКЦИИ
1. Приоритет информации из ГАРАНТ
2. Цитируй конкретные статьи и пункты
3. Указывай ссылки на источники (URL)
4. Дополняй информацией из документов дела

# ОГРАНИЧЕНИЯ (GUARDRAILS)
- НЕ давай устаревшую информацию
- ВСЕГДА указывай источник (статья, закон, URL)
- Используй Markdown для форматирования""",
            
            "draft": """# РОЛЬ
Ты — юрист, помогающий создавать документы.

# ЦЕЛЬ
Помочь пользователю создать профессиональный юридический документ.

# ИНСТРУКЦИИ
1. Уточни детали, если информации недостаточно
2. Используй стандартную структуру документа
3. Отмечай места для заполнения как [ЗАПОЛНИТЬ]

# ОГРАНИЧЕНИЯ (GUARDRAILS)
- НЕ выдумывай реквизиты и даты
- Предупреждай о необходимости проверки юристом"""
        }
        
        system_prompt = system_prompts.get(mode, system_prompts["normal"])
        
        # Формируем контекст
        context_parts = []
        
        # Добавляем профиль пользователя из Store (долгосрочная память)
        if user_profile:
            profile_context = []
            if isinstance(user_profile, dict):
                if user_profile.get("legal_preferences"):
                    prefs = user_profile["legal_preferences"]
                    if prefs.get("primary_area"):
                        profile_context.append(f"Основная область: {prefs['primary_area']}")
                    if prefs.get("preferred_style"):
                        profile_context.append(f"Стиль общения: {prefs['preferred_style']}")
                if user_profile.get("expertise_level"):
                    profile_context.append(f"Уровень экспертизы: {user_profile['expertise_level']}")
            if profile_context:
                context_parts.append(f"=== ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ===\n" + "\n".join(profile_context))
        
        # Добавляем summary предыдущего диалога если есть
        if message_summary:
            context_parts.append(f"=== КОНТЕКСТ ПРЕДЫДУЩЕГО ДИАЛОГА ===\n{message_summary}")
        
        if rag_context:
            context_parts.append(f"=== ДОКУМЕНТЫ ДЕЛА ===\n{rag_context}")
        
        if garant_context:
            context_parts.append(f"=== РЕЗУЛЬТАТЫ ГАРАНТ ===\n{garant_context}")
        
        if thinking_steps:
            thinking_text = "\n".join([f"Шаг {s['step_number']}: {s['content']}" for s in thinking_steps])
            context_parts.append(f"=== ПРОЦЕСС АНАЛИЗА ===\n{thinking_text}")
        
        if document_context:
            context_parts.append(f"=== ДОКУМЕНТ В РЕДАКТОРЕ ===\n{document_context[:5000]}")
        
        if selected_text:
            context_parts.append(f"=== ВЫДЕЛЕННЫЙ ТЕКСТ ===\n{selected_text}")
        
        full_context = "\n\n".join(context_parts) if context_parts else "Контекст не найден."
        
        # Генерируем ответ
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"КОНТЕКСТ:\n{full_context}\n\nВОПРОС:\n{question}")
        ]
        
        response = llm.invoke(messages)
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        new_state["response"] = response_text
        new_state["messages"] = [AIMessage(content=response_text)]
        
        logger.info(f"[GenerateResponse] Generated response: {len(response_text)} chars")
        
        # Сохраняем insights в Store для долгосрочной памяти
        if store and user_id:
            try:
                from datetime import datetime
                # Сохраняем insight о типе вопроса и режиме
                insight_key = f"insight_{datetime.utcnow().isoformat()}"
                insight_data = {
                    "type": mode,
                    "question": question[:200],  # Первые 200 символов
                    "response_length": len(response_text),
                    "has_rag_context": bool(rag_context),
                    "has_garant_context": bool(garant_context),
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                if hasattr(store, 'put'):
                    # Синхронный API
                    store.put(("memory", user_id), insight_key, insight_data)
                    logger.debug(f"[GenerateResponse] Saved insight to Store: {insight_key}")
                # Примечание: generate_response_node не async, поэтому используем только sync API
                # Если нужен async API, нужно сделать функцию async
            except Exception as store_e:
                logger.debug(f"[GenerateResponse] Could not save insight to Store: {store_e}")
        
    except Exception as e:
        logger.error(f"[GenerateResponse] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Generation error: {str(e)}"]
        new_state["response"] = f"Ошибка генерации ответа: {str(e)}"
    
    return new_state


def generate_draft_plan_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Узел генерации плана документа для HITL.
    
    Генерирует план документа перед созданием, чтобы пользователь мог его подтвердить.
    Этот узел выполняется перед draft_node (который прерывается через interrupt_before).
    """
    question = state.get("question", "")
    
    logger.info("[GenerateDraftPlan] Generating plan for document")
    
    new_state = dict(state)
    
    try:
        from app.services.llm_factory import create_legal_llm
        
        llm = create_legal_llm(use_rate_limiting=False)
        
        # Генерируем план документа
        plan_prompt = f"""На основе описания создай план юридического документа.

ОПИСАНИЕ:
{question}

Создай структурированный план документа в формате JSON:
{{
    "title": "Название документа",
    "type": "Тип документа (договор, заявление, и т.д.)",
    "sections": [
        {{"name": "Название раздела", "description": "Описание содержимого"}},
        ...
    ],
    "required_fields": ["Поле 1", "Поле 2", ...],
    "estimated_length": "Краткая/Средняя/Длинная"
}}

Ответь только JSON без дополнительных комментариев.
"""
        
        plan_response = llm.invoke([HumanMessage(content=plan_prompt)])
        plan_text = plan_response.content if hasattr(plan_response, 'content') else "{}"
        
        # Парсим JSON план
        try:
            import json
            draft_plan = json.loads(plan_text)
        except json.JSONDecodeError:
            # Fallback: создаём простой план
            draft_plan = {
                "title": question[:50] if len(question) > 50 else question,
                "type": "Юридический документ",
                "sections": [{"name": "Основной раздел", "description": "Содержимое документа"}],
                "required_fields": [],
                "estimated_length": "Средняя"
            }
        
        new_state["draft_plan"] = draft_plan
        new_state["response"] = f"""📋 План документа:

**Название:** {draft_plan.get('title', 'Новый документ')}
**Тип:** {draft_plan.get('type', 'Не указан')}
**Разделы:** {len(draft_plan.get('sections', []))}
**Ожидаемая длина:** {draft_plan.get('estimated_length', 'Не указана')}

Подтвердите создание документа или отмените операцию."""
        new_state["messages"] = [AIMessage(content=new_state["response"])]
        new_state["waiting_for_approval"] = True
        
        logger.info(f"[GenerateDraftPlan] Plan generated, waiting for approval")
        
    except Exception as e:
        logger.error(f"[GenerateDraftPlan] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Plan generation error: {str(e)}"]
        new_state["response"] = f"❌ Ошибка генерации плана: {str(e)}"
    
    return new_state


def draft_node(
    state: ChatGraphState,
    config: Dict[str, Any] = None,
    db: Session = None
) -> ChatGraphState:
    """
    Узел создания документа (draft mode).
    
    С HITL: сначала генерирует план документа для подтверждения пользователем.
    После подтверждения создаёт документ.
    
    # ПАТТЕРН: HITL через interrupt_before
    Граф прерывается перед этим узлом (interrupt_before=["draft"]),
    что позволяет пользователю подтвердить план перед созданием документа.
    
    Args:
        state: Состояние графа
        config: Конфигурация (может содержать информацию о прерывании)
        db: SQLAlchemy session
    """
    question = state.get("question", "")
    case_id = state.get("case_id")
    user_id = state.get("user_id")
    
    # Проверяем, был ли граф прерван (HITL)
    # План уже должен быть сгенерирован в generate_draft_plan_node
    draft_approved = state.get("draft_approved", False)
    draft_plan = state.get("draft_plan")
    
    new_state = dict(state)
    
    # Если план не найден, возвращаем ошибку
    if not draft_plan:
        logger.error(f"[Draft] Plan not found in state")
        new_state["errors"] = (new_state.get("errors") or []) + ["Plan not found"]
        new_state["response"] = "❌ Ошибка: план документа не найден"
        return new_state
    
    # Если план не подтверждён, возвращаем план снова (для случая, если граф не был прерван)
    if not draft_approved:
        logger.info(f"[Draft] Plan exists but not approved, returning plan")
        new_state["response"] = f"""📋 План документа (ожидает подтверждения):

**Название:** {draft_plan.get('title', 'Новый документ')}
**Тип:** {draft_plan.get('type', 'Не указан')}

Подтвердите создание документа или отмените операцию."""
        new_state["messages"] = [AIMessage(content=new_state["response"])]
        new_state["waiting_for_approval"] = True
        return new_state
    
    try:
        from app.services.document_editor_service import DocumentEditorService
        from app.services.llm_factory import create_legal_llm
        
        llm = create_legal_llm(use_rate_limiting=False)
        
        # План подтверждён - создаём документ
        logger.info(f"[Draft] Plan approved, creating document for case {case_id}")
        
        title = draft_plan.get("title", "Новый документ")
        if not title or len(title) < 3:
            title = "Новый документ"
        
        # Генерируем содержимое документа на основе плана
        sections_text = "\n".join([
            f"- {s.get('name', 'Раздел')}: {s.get('description', '')}"
            for s in draft_plan.get("sections", [])
        ])
        
        content_prompt = f"""Создай юридический документ на основе плана.

НАЗВАНИЕ: {title}
ТИП: {draft_plan.get('type', 'Юридический документ')}

РАЗДЕЛЫ:
{sections_text}

ОПИСАНИЕ: {question}

Создай профессиональный юридический документ в формате HTML.
Используй стандартную структуру для данного типа документа.
Включи все необходимые разделы и поля для заполнения (отметь их как [ЗАПОЛНИТЬ]).

Ответь только HTML-кодом документа без дополнительных комментариев.
"""
        
        content_response = llm.invoke([HumanMessage(content=content_prompt)])
        content = content_response.content if hasattr(content_response, 'content') else ""
        
        # Сохраняем документ
        doc_service = DocumentEditorService(db)
        document = doc_service.create_document(
            case_id=case_id,
            user_id=user_id,
            title=title,
            content=content
        )
        
        new_state["document_created"] = {
            "id": str(document.id),
            "title": document.title,
            "preview": content[:500] if content else ""
        }
        new_state["response"] = f'✅ Документ "{document.title}" успешно создан!'
        new_state["messages"] = [AIMessage(content=new_state["response"])]
        new_state["waiting_for_approval"] = False
        
        logger.info(f"[Draft] Document created: {document.id}")
            
    except Exception as e:
        logger.error(f"[Draft] Error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Draft error: {str(e)}"]
        new_state["response"] = f"❌ Ошибка создания документа: {str(e)}"
        new_state["waiting_for_approval"] = False
    
    return new_state


# ============== Routing Functions ==============

def route_by_mode(state: ChatGraphState) -> str:
    """Определить следующий узел на основе режима."""
    mode = state.get("mode", "normal")
    
    if mode == "draft":
        return "draft"  # Возвращаем ключ для conditional_edges, который ведёт к generate_draft_plan
    elif mode == "deep_think":
        return "thinking"  # Возвращаем ключ для conditional_edges
    elif mode == "garant":
        return "garant_retrieval"  # Возвращаем ключ для conditional_edges
    else:
        return "rag_retrieval"  # Возвращаем ключ для conditional_edges


def route_after_rag(state: ChatGraphState) -> str:
    """Определить следующий узел после RAG retrieval."""
    mode = state.get("mode", "normal")
    enable_garant = state.get("enable_garant", True)
    
    if mode == "garant" or (mode == "normal" and enable_garant):
        return "garant_retrieval"
    else:
        return "generate_response"


def route_after_garant(state: ChatGraphState) -> str:
    """Определить следующий узел после ГАРАНТ retrieval."""
    mode = state.get("mode", "normal")
    
    if mode == "deep_think":
        return "thinking"
    else:
        return "generate_response"


def route_after_thinking(state: ChatGraphState) -> str:
    """Определить следующий узел после thinking."""
    return "generate_response"


# ============== Graph Builder ==============

def create_chat_graph(
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None,
    use_checkpointing: bool = True,
    enable_memory_management: bool = True,
    interrupt_before: List[str] = None,
    interrupt_after: List[str] = None
):
    """
    Создать LangGraph граф для страницы чата.
    
    Args:
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
        use_checkpointing: Использовать checkpointing
        enable_memory_management: Включить управление памятью сообщений
        interrupt_before: Узлы для прерывания перед выполнением (HITL)
        interrupt_after: Узлы для прерывания после выполнения (HITL)
    
    Returns:
        Compiled LangGraph
    
    # АРХИТЕКТУРА ГРАФА (с memory management)
    ```
    START
      ↓
    manage_memory (опционально, обрезка/summarization)
      ↓
    mode_router (определяет режим)
      ↓
      ├── draft → draft_node → END
      │
      └── normal/deep_think/garant
            ↓
          rag_retrieval (поиск в документах дела)
            ↓
          garant_retrieval (поиск в ГАРАНТ, если включён)
            ↓
            ├── deep_think → thinking_node → generate_response → END
            │
            └── normal/garant → generate_response → END
    ```
    """
    logger.info("[ChatGraph] Creating chat graph")
    
    # Создаём граф
    graph = StateGraph(ChatGraphState)
    
    # Создаём wrapper функции с замыканием для db и rag_service
    def rag_retrieval_wrapper(state):
        return rag_retrieval_node(state, rag_service, db)
    
    def generate_response_wrapper(state):
        return generate_response_node(state, db)
    
    def draft_wrapper(state):
        return draft_node(state, db)
    
    # Добавляем узлы
    if enable_memory_management:
        graph.add_node("manage_memory", manage_memory_node)
    graph.add_node("mode_router", mode_router_node)
    graph.add_node("parallel_retrieval", parallel_retrieval_node)  # Параллельный запуск RAG и ГАРАНТ
    graph.add_node("rag_retrieval", rag_retrieval_wrapper)
    graph.add_node("garant_retrieval", garant_retrieval_node)
    graph.add_node("merge_retrieval_results", merge_retrieval_results_node)  # Объединение результатов
    graph.add_node("thinking", thinking_node)
    graph.add_node("generate_response", generate_response_wrapper)
    graph.add_node("generate_draft_plan", generate_draft_plan_node)  # Генерация плана перед draft
    graph.add_node("draft", draft_wrapper)
    
    # Добавляем рёбра
    if enable_memory_management:
        graph.add_edge(START, "manage_memory")
        graph.add_edge("manage_memory", "mode_router")
    else:
        graph.add_edge(START, "mode_router")
    
    # Conditional edge после mode_router
    graph.add_conditional_edges(
        "mode_router",
        route_by_mode,
        {
            "draft": "generate_draft_plan",  # draft mode -> генерируем план
            "thinking": "parallel_retrieval",  # deep_think mode -> параллельный поиск
            "garant_retrieval": "parallel_retrieval",  # garant mode -> параллельный поиск
            "rag_retrieval": "parallel_retrieval"  # normal mode -> параллельный поиск
        }
    )
    
    # Edge от generate_draft_plan к draft (прерывается через interrupt_before)
    graph.add_edge("generate_draft_plan", "draft")
    
    # Send API: parallel_retrieval возвращает List[Send], которые параллельно вызывают
    # rag_retrieval и garant_retrieval. После завершения всех Send выполнений,
    # нужно добавить edges от Send узлов к merge узлу.
    # Результаты собираются через reducers в state.
    graph.add_edge("rag_retrieval", "merge_retrieval_results")
    graph.add_edge("garant_retrieval", "merge_retrieval_results")
    
    # Conditional edge после merge_retrieval_results
    graph.add_conditional_edges(
        "merge_retrieval_results",
        route_after_garant,  # Используем существующую функцию маршрутизации
        {
            "thinking": "thinking",
            "generate_response": "generate_response"
        }
    )
    
    # Edge после thinking
    graph.add_edge("thinking", "generate_response")
    
    # Edge после draft
    graph.add_edge("draft", END)
    
    # Edge после generate_response
    graph.add_edge("generate_response", END)
    
    # Компилируем граф с input/output schemas и breakpoints
    compile_kwargs = {
        "input": ChatGraphInputState,
        "output": ChatGraphOutputState,
    }
    
    # Добавляем breakpoints если указаны
    # По умолчанию прерываем перед draft для HITL (подтверждение перед созданием документа)
    if interrupt_before is None:
        interrupt_before = ["draft"]  # По умолчанию HITL для draft mode
        logger.info("[ChatGraph] Using default interrupt_before=['draft'] for HITL")
    
    if interrupt_before:
        compile_kwargs["interrupt_before"] = interrupt_before
        logger.info(f"[ChatGraph] interrupt_before: {interrupt_before}")
    if interrupt_after:
        compile_kwargs["interrupt_after"] = interrupt_after
        logger.info(f"[ChatGraph] interrupt_after: {interrupt_after}")
    
    # Получаем Store для долгосрочной памяти
    store = get_store_instance()
    if store:
        compile_kwargs["store"] = store
        logger.info("[ChatGraph] Store integrated for long-term memory")
    
    if use_checkpointing:
        try:
            checkpointer = get_checkpointer_instance()
            compiled = graph.compile(checkpointer=checkpointer, **compile_kwargs)
            logger.info("[ChatGraph] Compiled with PostgresSaver checkpointer, Store and input/output schemas")
        except Exception as e:
            logger.warning(f"[ChatGraph] Failed to get PostgresSaver, using MemorySaver: {e}")
            compiled = graph.compile(checkpointer=MemorySaver(), **compile_kwargs)
    else:
        compiled = graph.compile(**compile_kwargs)
    
    logger.info("[ChatGraph] Graph created successfully")
    return compiled



